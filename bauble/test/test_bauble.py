# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Tests for the main bauble module.
"""
import datetime
import logging
import os
import time
from unittest import mock

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy.exc import StatementError

import bauble
from bauble import db
from bauble import meta
from bauble import prefs
from bauble import utils
from bauble.btypes import CustomEnum
from bauble.btypes import Enum
from bauble.btypes import EnumError
from bauble.btypes import date_parser
from bauble.test import BaubleTestCase
from bauble.test import check_dupids


class EnumTests(BaubleTestCase):
    table = None

    def setUp(self):
        super().setUp()
        if self.__class__.table is None:

            class Test(db.Base):
                __tablename__ = "test_enum_type"
                id = Column(Integer, primary_key=True)
                value = Column(Enum(values=["1", "2", ""]), default="")

            self.__class__.Test = Test
            self.__class__.table = Test.__table__
            self.table.create(bind=db.engine)

    def tearDown(self):
        super().tearDown()

    def test_insert_low_level(self):
        db.engine.execute(self.table.insert(), {"id": 1})

    def test_insert_alchemic(self):
        t = self.Test(id=1)
        self.session.add(t)
        self.session.flush()

    def test_insert_by_value_ok(self):
        t = self.Test(value="1")
        self.session.add(t)
        self.session.flush()

    def test_insert_by_value_wrong_value_seen_late(self):
        t = self.Test(value="33")
        self.session.add(t)
        self.assertRaises(StatementError, self.session.flush)

    def function_creating_enum(self, name, values, **kwargs):
        self.Table = type(
            "test_table_" + name,
            (db.Base,),
            {
                "__tablename__": "test_enum_type_" + name,
                "id": Column(Integer, primary_key=True),
                "value": Column(Enum(values=values, **kwargs), default=""),
            },
        )
        self.table = self.Table.__table__
        self.table.create(bind=db.engine)

    def test_bad_enum(self):
        self.function_creating_enum(
            "zero",
            [
                "1",
                "2",
                "3",
            ],
        )
        self.assertRaises(EnumError, self.function_creating_enum, "one", [])
        self.assertRaises(EnumError, self.function_creating_enum, "two", None)
        self.assertRaises(
            EnumError, self.function_creating_enum, "three", [1, ""]
        )  # int can't be
        self.assertRaises(
            EnumError,
            self.function_creating_enum,
            "four",
            [
                "1",
                "1",
            ],
        )  # same value twice
        self.assertRaises(
            EnumError, self.function_creating_enum, "five", ["1", [], None]
        )  # strings please
        self.assertRaises(
            EnumError,
            self.function_creating_enum,
            "six",
            ["1", "2"],
            empty_to_none=True,
        )  # no empty

    def test_empty_to_none(self):
        self.function_creating_enum("seven", ["1", None], empty_to_none=True)
        t = self.Table(value="1")
        self.session.add(t)
        t = self.Table(value="")
        self.session.add(t)
        self.session.flush()
        q = self.session.query(self.Table).filter_by(value="")
        self.assertEqual(q.all(), [])
        q = self.session.query(self.Table).filter_by(value=None)
        self.assertEqual(q.all(), [t])

    def test_comparator(self):
        pos_vals = ("testA", "testB", "testZ", None)

        class TestTableComparator(db.Base):
            __tablename__ = "test_table_comparator"
            value = Column(Enum(values=pos_vals, empty_to_none=True))

        TestTableComparator.__table__.create(bind=db.engine)

        test1 = TestTableComparator(value="testZ")
        test2 = TestTableComparator(value="testA")
        test3 = TestTableComparator(value="")
        self.session.add_all([test1, test2, test3])
        self.session.commit()
        self.assertIsNone(test3.value)
        gt_b = (
            self.session.query(TestTableComparator)
            .filter(TestTableComparator.value > "testB")
            .all()
        )
        self.assertEqual(gt_b, [test2])
        # should be less than alphabetically
        self.assertLess(gt_b[0].value, "testB")
        lt_b = (
            self.session.query(TestTableComparator)
            .filter(TestTableComparator.value < "testB")
            .all()
        )
        self.assertCountEqual(lt_b, [test1, test3])
        ge_b = (
            self.session.query(TestTableComparator)
            .filter(TestTableComparator.value >= "testB")
            .all()
        )
        self.assertEqual(ge_b, [test2])
        # should be less than alphabetically
        self.assertLess(ge_b[0].value, "testB")
        le_b = (
            self.session.query(TestTableComparator)
            .filter(TestTableComparator.value <= "testB")
            .all()
        )
        self.assertCountEqual(le_b, [test1, test3])
        eq_a = (
            self.session.query(TestTableComparator)
            .filter(TestTableComparator.value == "testA")
            .all()
        )
        self.assertEqual(eq_a, [test2])
        in_a_z = (
            self.session.query(TestTableComparator)
            .filter(TestTableComparator.value.in_(("testA", "testZ")))
            .all()
        )
        self.assertCountEqual(in_a_z, [test1, test2])
        # still works in a subquery
        test4 = TestTableComparator(value="testB")
        self.session.add(test4)
        self.session.commit()
        subq = (
            self.session.query(TestTableComparator.value)
            .filter(TestTableComparator.id == test4.id)
            .scalar_subquery()
        )
        qry = (
            self.session.query(TestTableComparator)
            .filter(TestTableComparator.value > subq)
            .all()
        )
        self.assertEqual(qry, [test2])

    def test_custom_enum_delays_init(self):
        class TestTableCustom(db.Base):
            __tablename__ = "test_table_custom"
            value = Column(CustomEnum(12))

        TestTableCustom.__table__.create(bind=db.engine)

        # prior to init behaves as standard unicode column
        prior = TestTableCustom(value="blah")
        self.session.add(prior)
        self.session.commit()
        self.assertEqual(prior.value, "blah")
        self.session.delete(prior)
        self.session.commit()

        enum = TestTableCustom.value.prop.columns[0].type
        pos_vals = ("testA", "testB", "testZ", None)
        enum.init(pos_vals, empty_to_none=True)
        self.assertEqual(enum.values, pos_vals)
        self.assertRaises(EnumError, enum.process_bind_param, "BLAH", None)

        self.session.close()
        db.open_conn(db.engine.url)
        self.session = db.Session()

        after = TestTableCustom(value="BLAH")
        self.session.add(after)
        self.assertRaises(StatementError, self.session.flush)
        self.session.rollback()

        # make sure comparator works after init
        test1 = TestTableCustom(value="testZ")
        test2 = TestTableCustom(value="testA")
        test3 = TestTableCustom(value="")
        self.session.add_all([test1, test2, test3])
        self.session.commit()
        self.assertIsNone(test3.value)
        gt_a = (
            self.session.query(TestTableCustom)
            .filter(TestTableCustom.value > "testB")
            .all()
        )
        self.assertEqual(gt_a, [test2])
        self.assertLess(gt_a[0].value, "testB")
        gt_a = (
            self.session.query(TestTableCustom)
            .filter(TestTableCustom.value < "testB")
            .all()
        )
        self.assertCountEqual(gt_a, [test1, test3])


class BaubleTests(BaubleTestCase):
    def test_date_type(self):
        """
        Test bauble.types.Date
        """
        dt = bauble.btypes.Date()

        bauble.btypes.Date._dayfirst = False
        bauble.btypes.Date._yearfirst = False
        s = "12-30-2008"
        v = dt.process_bind_param(s, None)
        self.assertTrue(
            v.month == 12 and v.day == 30 and v.year == 2008,
            "%s == %s" % (v, s),
        )

        bauble.btypes.Date._dayfirst = True
        bauble.btypes.Date._yearfirst = False
        s = "30-12-2008"
        v = dt.process_bind_param(s, None)
        self.assertTrue(
            v.month == 12 and v.day == 30 and v.year == 2008,
            "%s == %s" % (v, s),
        )

        bauble.btypes.Date._dayfirst = False
        bauble.btypes.Date._yearfirst = True
        s = "2008-12-30"
        v = dt.process_bind_param(s, None)
        self.assertTrue(
            v.month == 12 and v.day == 30 and v.year == 2008,
            "%s == %s" % (v, s),
        )

        # TODO: python-dateutil 1.4.1 has a bug where dayfirst=True,
        # yearfirst=True always parses as dayfirst=False

        # bauble.types.Date._dayfirst = True
        # bauble.types.Date._yearfirst = True
        # debug('--')
        # s = '2008-30-12'
        # #s = '2008-12-30'
        # debug(s)
        # v = dt.process_bind_param(s, None)
        # debug(v)
        # self.assert_(v.month==12 and v.day==30 and v.year==2008,
        #              '%s == %s' % (v, s))

    def test_datetime_type(self):
        """
        Test bauble.types.DateTime
        """
        from datetime import timezone

        dtime = bauble.btypes.DateTime()

        # with naive tz - assume UTC (datetime.utcnow(), sqlite func.now())
        now = utils.utcnow_naive()
        res = now.replace(tzinfo=timezone.utc).astimezone(tz=None)
        ret = dtime.process_result_value(now, None)
        self.assertEqual(res, ret)

        # with UTC and not naive tz (postgresql func.now())
        now = utils.utcnow_naive().replace(tzinfo=timezone.utc)
        res = now.astimezone(tz=None)
        ret = dtime.process_result_value(now, None)
        self.assertEqual(res, ret)

        # with local timezone
        now = datetime.datetime.now().astimezone(tz=None)
        ret = dtime.process_result_value(now, None)
        self.assertEqual(now, ret)

        # string values are always stored as utc
        string = "01-12-2021 11:50:01"
        ret = dtime.process_bind_param(string, None)
        self.assertEqual(ret.tzinfo, datetime.timezone.utc)
        # and don't change
        self.assertEqual(
            ret.astimezone().strftime("%d-%m-%Y %I:%M:%S"), string
        )

        # iso string value
        string = "2021-12-01 11:50:01"
        ret = dtime.process_bind_param(string, None)
        self.assertEqual(ret.tzinfo, datetime.timezone.utc)
        # and don't change
        self.assertEqual(
            ret.astimezone().strftime("%Y-%m-%d %I:%M:%S"), string
        )

        # datetime objects are returned as is if utc
        now = datetime.datetime.now().astimezone(tz=None)
        ret = dtime.process_bind_param(now, None)
        self.assertEqual(ret, now)
        now = utils.utcnow_naive()
        ret = dtime.process_bind_param(now, None)
        self.assertEqual(ret, now)

        # datetime objects in another timezone are converted to utc
        now = datetime.datetime.now().astimezone(
            datetime.timezone(datetime.timedelta(hours=9))
        )
        ret = dtime.process_bind_param(now, None)
        self.assertEqual(ret.tzinfo, datetime.timezone.utc)
        self.assertEqual(ret, now)

        # with junk text returns none
        text = "some random text"
        ret = dtime.process_bind_param(text, None)
        self.assertIsNone(ret)

    def test_date_parser(self):
        # with dayfirst
        string = "3-12-2008"
        val = date_parser(string)
        self.assertEqual(val.day, 3)
        self.assertEqual(val.month, 12)
        self.assertEqual(val.year, 2008)

        # with month first
        prefs.prefs[prefs.date_format_pref] = "%m-%d-%Y"
        string = "3-12-2008"
        val = date_parser(string)
        self.assertEqual(val.day, 12)
        self.assertEqual(val.month, 3)
        self.assertEqual(val.year, 2008)

        # iso
        string = "2008-12-03"
        val = date_parser(string)
        self.assertEqual(val.day, 3)
        self.assertEqual(val.month, 12)
        self.assertEqual(val.year, 2008)

        # fuzzy
        string = "Sunday the 3rd of August, 2025"
        val = date_parser(string)
        self.assertEqual(val.day, 3)
        self.assertEqual(val.month, 8)
        self.assertEqual(val.year, 2025)

        # invalid
        self.assertIsNone(date_parser(object()))

    def test_bool_type(self):
        string = "True"
        boolean = bauble.btypes.Boolean()
        ret = boolean.process_bind_param(string, None)
        self.assertTrue(ret)

        string = "False"
        ret = boolean.process_bind_param(string, None)
        self.assertFalse(ret)

        string = "random"
        ret = boolean.process_bind_param(string, None)
        self.assertIsNone(ret)

        ret = boolean.process_bind_param(False, None)
        self.assertFalse(ret)

        ret = boolean.process_bind_param(True, None)
        self.assertTrue(ret)

    def test_truncated_string_type(self):
        string = "x" * 10
        trunc_string = bauble.btypes.TruncatedString(10)
        ret = trunc_string.process_bind_param(string, None)
        self.assertEqual(ret, string)

        long_string = string + "y"
        ret = trunc_string.process_bind_param(long_string, None)
        self.assertEqual(ret, string)

        long_string = string + "y" * 10
        ret = trunc_string.process_bind_param(long_string, None)
        self.assertEqual(ret, string)

        short_string = "x"
        ret = trunc_string.process_bind_param(short_string, None)
        self.assertEqual(ret, short_string)

    def test_base_table(self):
        """
        Test db.Base is setup correctly
        """
        m = meta.BaubleMeta(name="name", value="value")
        self.session.add(m)
        self.session.commit()
        m = self.session.query(meta.BaubleMeta).filter_by(name="name").first()

        # test that _created and _last_updated were created correctly
        self.assertTrue(
            hasattr(m, "_created")
            and isinstance(m._created, datetime.datetime)
        )
        self.assertTrue(
            hasattr(m, "_last_updated")
            and isinstance(m._last_updated, datetime.datetime)
        )

        # test that created does not change when the value is updated
        # but that last_updated does
        created = m._created
        last_updated = m._last_updated
        # sleep for one second before committing since the DateTime
        # column only has one second granularity
        time.sleep(1.1)
        m.value = "value2"
        self.session.commit()
        self.session.expire(m)
        self.assertTrue(isinstance(m._created, datetime.datetime))
        self.assertTrue(m._created == created)
        self.assertTrue(isinstance(m._last_updated, datetime.datetime))
        self.assertTrue(m._last_updated != last_updated)

    def test_duplicate_ids(self):
        """
        Test for duplicate ids for all .glade files in the bauble module
        """
        import glob

        import bauble as mod

        head, tail = os.path.split(mod.__file__)
        files = glob.glob(os.path.join(head, "*.glade"))
        for f in files:
            ids = check_dupids(f)
            self.assertTrue(
                ids == [], "%s has duplicate ids: %s" % (f, str(ids))
            )


class HistoryTests(BaubleTestCase):
    def test(self):
        """
        Test the HistoryMapperExtension
        """
        # sleep required for windows tests to succeed due to 16ms resolution
        from time import sleep

        from bauble.plugins.plants import Family

        sleep(0.02)
        f = Family(family="Family")
        self.session.add(f)
        self.session.commit()
        history = (
            self.session.query(db.History)
            .order_by(db.History.timestamp.desc())
            .first()
        )
        self.assertEqual(history.table_name, "family")
        self.assertEqual(history.operation, "insert")

        sleep(0.02)
        # # NOTE need to refresh to avoid single item list changes
        self.session.refresh(f)
        f.family = "Family2"
        self.session.commit()
        history = (
            self.session.query(db.History)
            .order_by(db.History.timestamp.desc())
            .first()
        )
        self.assertEqual(history.table_name, "family")
        self.assertEqual(history.operation, "update")

        sleep(0.02)
        self.session.delete(f)
        self.session.commit()
        history = (
            self.session.query(db.History)
            .order_by(db.History.timestamp.desc())
            .first()
        )
        self.assertEqual(history.table_name, "family")
        self.assertEqual(history.operation, "delete")


class MVPTests(BaubleTestCase):
    def test_can_programmatically_connect_signals(self):
        from bauble.editor import GenericEditorPresenter
        from bauble.editor import GenericEditorView

        class HandlerDefiningPresenter(GenericEditorPresenter):
            def on_tag_desc_textbuffer_changed(self, *args):
                pass

        model = db.History()
        import tempfile

        handle, fn = tempfile.mkstemp()
        os.close(handle)
        with open(fn, "w") as ntf:
            ntf.write(
                """\
<interface>
  <requires lib="gtk+" version="2.24"/>
  <!-- interface-naming-policy toplevel-contextual -->
  <object class="GtkDialog" id="handler-defining-view"/>
</interface>
"""
            )
        view = GenericEditorView(fn, None, "handler-defining-view")
        presenter = HandlerDefiningPresenter(model, view)
        natural_number_for_dialog_box = len(
            presenter.view._GenericEditorView__attached_signals
        )
        handle, fn = tempfile.mkstemp()
        os.close(handle)
        with open(fn, "w") as ntf:
            ntf.write(
                """\
<interface>
  <requires lib="gtk+" version="2.24"/>
  <!-- interface-naming-policy toplevel-contextual -->
  <object class="GtkTextBuffer" id="tag_desc_textbuffer">
    <signal name="changed" handler="on_tag_desc_textbuffer_changed" swapped="no"/>
  </object>
  <object class="GtkDialog" id="handler-defining-view"/>
</interface>
"""
            )
        view = GenericEditorView(fn, None, "handler-defining-view")
        presenter = HandlerDefiningPresenter(model, view)
        self.assertEqual(
            len(presenter.view._GenericEditorView__attached_signals),
            natural_number_for_dialog_box + 1,
        )
        presenter.on_tag_desc_textbuffer_changed()  # avoid uncounted line!


class GlobalFunctionsTests(BaubleTestCase):
    @mock.patch("bauble.gui")
    def test_command_handler(self, mock_gui):
        bauble.command_handler("history", None)
        mock_gui.get_view.assert_called()

        from bauble.view import HistoryView
        from bauble.view import PrefsView
        from bauble.view import SearchView

        mock_gui.set_view.assert_called()
        self.assertIsInstance(mock_gui.set_view.call_args[0][0], HistoryView)
        mock_gui.reset_mock()

        # switch to default
        bauble.command_handler(None, None)
        mock_gui.set_view.assert_called()
        self.assertIsInstance(mock_gui.set_view.call_args[0][0], SearchView)
        mock_gui.reset_mock()

        # switch to prefs
        bauble.command_handler("prefs", None)
        mock_gui.set_view.assert_called()
        self.assertIsInstance(mock_gui.set_view.call_args[0][0], PrefsView)

        # test key errors
        from bauble import pluginmgr

        # temporarily remove the default command handler
        start = pluginmgr.commands[None]

        del pluginmgr.commands[None]

        with mock.patch("bauble.utils.message_dialog") as mock_dialog:
            bauble.command_handler(None, None)
            mock_dialog.assert_called_with("No default handler registered")
            mock_dialog.reset_mock()
            bauble.command_handler("NOTaCOMMAND", None)
            mock_dialog.assert_called_with(
                "No command handler for NOTaCOMMAND"
            )

        pluginmgr.commands[None] = start
