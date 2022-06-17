# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2016 Mario Frasca <mario@anche.no>
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
#
# test.py
#
# Description: test the ABCD (Access to Biological Collection Data) plugin
#
import datetime
import lxml.etree as etree
import os
import tempfile

from unittest import mock

import logging
logger = logging.getLogger(__name__)

import bauble.paths as paths
from bauble.test import BaubleTestCase
import bauble.plugins.abcd as abcd
from bauble.plugins.garden import Plant, Accession, Source, Collection
import bauble.plugins.plants.test_plants as plants_test
import bauble.plugins.garden.test_garden as garden_test


# TODO: the ABCD tests need to be completely reworked

class ABCDTestCase(BaubleTestCase):

    def __init__(self, *args):
        super().__init__(*args)

    def setUp(self):
        super().setUp()
        plants_test.setUp_data()
        garden_test.setUp_data()

        schema_file = os.path.join(
            paths.lib_dir(), 'plugins', 'abcd', 'abcd_2.06.xsd')
        xmlschema_doc = etree.parse(schema_file)
        self.abcd_schema = etree.XMLSchema(xmlschema_doc)

    @mock.patch('bauble.utils.message_dialog')
    def test_export(self, mock_dialog):
        """Test the ABCDExporter.  If message_dialog is called fail. i.e.
        validation fails"""
        self.assertTrue(self.session.query(Plant).count() > 0)
        accession = self.session.query(Accession).first()
        source = Source()
        accession.source = source
        source.sources_code = '1'
        collection = Collection(collector='Bob',
                                collectors_code='1',
                                geography_id=1,
                                locale='locale',
                                date=datetime.date.today(),
                                latitude='1.1',
                                longitude='1.1',
                                geo_accy=1.1,
                                habitat='habitat description',
                                elevation=1,
                                elevation_accy=1,
                                notes='some notes')
        source.collection = collection
        self.session.commit()
        handle, filename = tempfile.mkstemp()
        abcd.ABCDExporter().start(filename)
        os.close(handle)
        mock_dialog.assert_not_called()

    def test_plants_to_abcd(self):
        plants = self.session.query(Plant)
        assert plants.count() > 0
        pass
        # create abcd from plants
        # data = abcd.plants_to_abcd(plants)
        # assert validate abcd
        # self.assert_(self.validate(data), self.abcd_schema.error_log)

    def validate(self, xml):
        return self.abcd_schema.validate(xml)
