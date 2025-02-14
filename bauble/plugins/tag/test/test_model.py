# pylint: disable=no-self-use,protected-access
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
Tag model tests
"""

from time import sleep

from bauble import db
from bauble import error
from bauble.plugins.plants import Family
from bauble.test import BaubleTestCase

from ..model import Tag
from ..model import TaggedObj
from ..model import _classname
from ..model import _get_tagged_object_pair
from ..model import get_tag_ids
from ..model import tag_objects
from ..model import untag_objects


class TagTests(BaubleTestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setUp(self):
        super().setUp()
        self.family = Family(family="family")
        self.session.add(self.family)
        self.session.commit()

    def test_str(self):
        name = "test"
        tag = Tag(tag=name)
        self.assertEqual(str(tag), name)

    def test_str_detached(self):
        tag = Tag(tag="Foo")
        with db.Session() as sess:
            sess.add(tag)
            sess.commit()
        self.assertRegex(str(tag), "<.*Tag object at .*>")

    def test_markup(self):
        tag = Tag(tag="Foo")
        self.assertEqual(tag.markup(), "Foo Tag")

    def test_tagged_obj_str(self):
        name = "test"
        tag = Tag(tag=name)
        obj = Family(epithet="Foo")
        self.session.add_all([tag, obj])
        self.session.commit()
        tagged_obj = TaggedObj(
            obj_id=obj.id, obj_class=_classname(obj), tag=tag
        )
        tag.objects_.append(tagged_obj)
        self.assertEqual(str(tagged_obj), f"{_classname(obj)}: {obj.id}")

    def test_tag_nothing(self):
        t = Tag(tag="some_tag", description="description")
        self.session.add(t)
        self.session.commit()
        t.tag_objects([])
        self.assertEqual(t.objects, [])
        self.assertEqual(
            t.search_view_markup_pair(),
            (
                'some_tag - <span weight="light">tagging nothing</span>',
                '(Tag) - <span weight="light">description</span>',
            ),
        )

    def test_is_tagging(self):
        family2 = Family(family="family2")
        t1 = Tag(tag="test1")
        self.session.add_all([family2, t1])
        self.session.commit()
        self.assertFalse(t1.is_tagging(family2))
        self.assertFalse(t1.is_tagging(self.family))

        # required for windows tests to succeed due to 16ms resolution
        sleep(0.02)
        t1.tag_objects([self.family])
        self.session.commit()
        self.assertFalse(t1.is_tagging(family2))
        self.assertTrue(t1.is_tagging(self.family))

    def test_search_view_markup_pair(self):
        family2 = Family(family="family2")
        t1 = Tag(tag="test1")
        t2 = Tag(tag="test2")
        self.session.add_all([family2, t1, t2])
        self.session.commit()
        t1.tag_objects([self.family, family2])
        t2.tag_objects([self.family])
        self.assertEqual(
            t1.search_view_markup_pair(),
            (
                'test1 - <span weight="light">tagging 2 objects of type '
                "Family</span>",
                '(Tag) - <span weight="light"></span>',
            ),
        )
        self.assertEqual(
            t2.search_view_markup_pair(),
            (
                'test2 - <span weight="light">tagging 1 objects of type '
                "Family</span>",
                '(Tag) - <span weight="light"></span>',
            ),
        )

        # required for windows tests to succeed due to 16ms resolution (also
        # timed cache)
        sleep(0.3)
        t2.tag_objects([t1])
        self.session.commit()
        self.assertEqual(
            t2.search_view_markup_pair(),
            (
                'test2 - <span weight="light">tagging 2 objects of 2 '
                "different types: Family, Tag</span>",
                '(Tag) - <span weight="light"></span>',
            ),
        )

    def test_get_tagged_objects_deletes_redundant(self):
        family2 = Family(family="family2")
        t1 = Tag(tag="test1")
        self.session.add_all([family2, t1])
        self.session.commit()
        self.assertFalse(t1.is_tagging(family2))
        self.assertFalse(t1.is_tagging(self.family))
        # required for windows tests to succeed due to 16ms resolution

        sleep(0.02)
        t1.tag_objects([self.family, family2])
        self.session.commit()
        self.assertEqual(len(t1.objects), 2)
        sleep(0.02)
        self.session.delete(family2)
        self.session.commit()
        self.assertEqual(len(t1.objects), 1)

    def test_retreive_tag(self):
        tag1 = Tag(tag="test1")
        tag2 = Tag(tag="test2")
        self.session.add_all([tag1, tag2])
        self.session.commit()

        keys = {
            "tag": "test1",
        }
        tag = Tag.retrieve(self.session, keys)
        self.assertEqual(tag, tag1)

    def test_retreive_tag_description_fails(self):
        tag1 = Tag(tag="test1")
        tag2 = Tag(tag="test2")
        self.session.add_all([tag1, tag2])
        self.session.commit()
        # fails due to keys
        keys = {
            "description": "",
        }
        tag = Tag.retrieve(self.session, keys)
        self.assertIsNone(tag)

    def test_retreive_tag_id_only(self):
        tag1 = Tag(tag="test1")
        tag2 = Tag(tag="test2")
        self.session.add_all([tag1, tag2])
        self.session.commit()
        keys = {"id": tag2.id}
        tag = Tag.retrieve(self.session, keys)
        self.assertEqual(tag, tag2)

    def test_retrieve_tag_doesnt_retreive_none_existent(self):
        tag1 = Tag(tag="test1")
        tag2 = Tag(tag="test2")
        self.session.add_all([tag1, tag2])
        self.session.commit()
        keys = {"tag": "Noneexistent"}
        tag = Tag.retrieve(self.session, keys)
        self.assertIsNone(tag)

    def test_tag_objects_no_object_session_bails(self):
        tag = Tag(tag="Foo")
        with self.assertLogs(level="WARNING") as logs:
            tag.tag_objects(self.family)
        self.assertEqual(tag.objects_, [])
        string = "no object session bailing."
        self.assertTrue(any(string in i for i in logs.output))


class AttachedToTests(BaubleTestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setUp(self):
        super().setUp()
        obj1 = Tag(tag="medicinal")
        obj2 = Tag(tag="maderable")
        obj3 = Tag(tag="frutal")
        fam = Family(family="Solanaceae")
        self.session.add_all([obj1, obj2, obj3, fam])
        self.session.commit()

    def test_attached_tags_empty(self):
        fam = self.session.query(Family).one()
        self.assertEqual(Tag.attached_to(fam), [])

    def test_attached_tags_singleton(self):
        fam = self.session.query(Family).one()
        obj2 = self.session.query(Tag).filter(Tag.tag == "maderable").one()
        tag_objects(obj2.tag, [fam])
        self.assertEqual(Tag.attached_to(fam), [obj2])

    def test_attached_tags_many(self):
        fam = self.session.query(Family).one()
        tags = self.session.query(Tag).all()
        for t in tags:
            tag_objects(t.tag, [fam])
        self.assertEqual(Tag.attached_to(fam), tags)

    def test_attached_to_no_object_session_bails(self):
        with self.assertLogs(level="WARNING") as logs:
            self.assertEqual(Tag.attached_to(Family(epithet="Foo")), [])

        string = "no object session bailing."
        self.assertTrue(any(string in i for i in logs.output))


class GetTagIdsTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        self.fam1 = Family(family="Fabaceae")
        self.fam2 = Family(family="Poaceae")
        self.fam3 = Family(family="Solanaceae")
        self.fam4 = Family(family="Caricaceae")
        self.session.add_all([self.fam1, self.fam2, self.fam3, self.fam4])
        self.session.commit()
        tag_objects("test1", [self.fam1, self.fam2])
        tag_objects("test2", [self.fam1])
        tag_objects("test3", [self.fam2, self.fam3])
        self.session.commit()

    def test_get_tag_ids1(self):
        s_all, s_some = get_tag_ids([self.fam1, self.fam2])
        self.assertEqual(s_all, set([1]))
        self.assertEqual(s_some, set([2, 3]))

    def test_get_tag_ids2(self):
        s_all, s_some = get_tag_ids([self.fam1])
        self.assertEqual(s_all, set([1, 2]))
        self.assertEqual(s_some, set([]))

    def test_get_tag_ids3(self):
        s_all, s_some = get_tag_ids([self.fam2])
        test_id = set([1, 3])
        self.assertEqual(s_all, test_id)
        self.assertEqual(s_some, set([]))

    def test_get_tag_ids4(self):
        s_all, s_some = get_tag_ids([self.fam3])
        test_id = set([3])
        self.assertEqual(s_all, test_id)
        self.assertEqual(s_some, set([]))

    def test_get_tag_ids5(self):
        s_all, s_some = get_tag_ids([self.fam1, self.fam3])
        test_id = set([])
        self.assertEqual(s_all, test_id)
        self.assertEqual(s_some, set([1, 2, 3]))

    def test_get_tag_ids6(self):
        s_all, s_some = get_tag_ids([self.fam1, self.fam4])
        self.assertEqual(s_all, set([]))
        self.assertEqual(s_some, set([1, 2]))

    def test_get_tag_ids7(self):
        for tag in self.session.query(Tag):
            self.session.delete(tag)
        self.session.commit()
        tag_objects("test1", [self.fam1, self.fam4])
        tag_objects("test2", [self.fam1])
        tag_objects("test3", [self.fam2, self.fam4])
        self.session.commit()
        tag_ids = self.session.query(Tag.id).filter(
            Tag.tag.in_(["test1", "test2", "test3"])
        )
        s_all, s_some = get_tag_ids(
            [self.fam1, self.fam2, self.fam3, self.fam4]
        )
        self.assertEqual(s_all, set([]))
        self.assertEqual(s_some, {i[0] for i in tag_ids})

    def test_no_object_session_raises(self):
        obj = Family(epithet="Foo")
        self.assertRaises(error.DatabaseError, get_tag_ids, [obj])


class GlobalFunctionsTest(BaubleTestCase):
    # tag_object untag_objects
    def test_get_tagged_object_pair(self):
        tag = Tag(tag="test")
        obj = Family(epithet="Foo")
        self.session.add_all([tag, obj])
        self.session.commit()
        tagged_obj = TaggedObj(
            obj_id=obj.id, obj_class="bauble.plugins.plants.Family", tag=tag
        )
        tag.objects_.append(tagged_obj)

        self.assertEqual(
            _get_tagged_object_pair(tagged_obj), (type(obj), obj.id)
        )

    def test_get_tagged_object_pair_error_logs(self):
        tag = Tag(tag="test")
        obj = Family(epithet="Foo")
        self.session.add_all([tag, obj])
        self.session.commit()
        tagged_obj = TaggedObj(
            obj_id=obj.id, obj_class="bauble.plugin.taxonomy.Family", tag=tag
        )
        tag.objects_.append(tagged_obj)

        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(_get_tagged_object_pair(tagged_obj))
        string = (
            f"get_tagged_object_pair ({tagged_obj}) error: ModuleNotFoundError"
        )
        self.assertTrue(any(string in i for i in logs.output))

        tagged_obj.obj_class = "bauble.plugins.plants.Taxon"
        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(_get_tagged_object_pair(tagged_obj))
        string = (
            f"_get_tagged_object_pair ({tagged_obj}) error: AttributeError"
        )
        self.assertTrue(any(string in i for i in logs.output))

        tagged_obj.obj_class = "Taxon"
        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(_get_tagged_object_pair(tagged_obj))
        string = f"_get_tagged_object_pair ({tagged_obj}) error: ValueError"
        self.assertTrue(any(string in i for i in logs.output))

    def test_tag_object_no_object_session_logs(self):
        tag = Tag(tag="test")
        obj = Family(epithet="Foo")
        self.session.add(tag)
        self.session.commit()
        with self.assertLogs(level="WARNING") as logs:
            tag_objects("test", [obj])
        string = "no object session bailing."
        self.assertTrue(any(string in i for i in logs.output))

    def test_untag_object_no_object_session_logs(self):
        tag = Tag(tag="test")
        obj = Family(epithet="Foo")
        self.session.add(tag)
        self.session.commit()
        with self.assertLogs(level="WARNING") as logs:
            untag_objects("test", [obj])
        string = "no object session bailing."
        self.assertTrue(any(string in i for i in logs.output))

    def test_untag_object_no_tag_logs(self):
        obj = Family(epithet="Foo")
        self.session.add(obj)
        self.session.commit()
        with self.assertLogs(level="INFO") as logs:
            untag_objects("test", [obj])
        string = "Can't remove non existing tag"
        self.assertTrue(any(string in i for i in logs.output))


class GlobalFunctionsTests(BaubleTestCase):

    def test_tag_untag_objects(self):
        family1 = Family(epithet="family1")
        family2 = Family(epithet="family2")
        self.session.add_all([family1, family2])
        self.session.commit()
        family1_id = family1.id
        family2_id = family2.id
        tag_objects("test", [family1, family2])

        tag = self.session.query(Tag).filter_by(tag="test").one()
        sorted_pairs = sorted([(type(o), o.id) for o in tag.objects])
        self.assertEqual(
            sorted([(Family, family1_id), (Family, family2_id)]), sorted_pairs
        )

        # required for windows tests to succeed due to 16ms resolution
        sleep(0.02)
        tag_objects("test", [family1, family2])
        self.assertEqual(tag.objects, [family1, family2])

        # first untag one
        sleep(0.02)
        untag_objects("test", [family1])

        # get object by tag
        tag = self.session.query(Tag).filter_by(tag="test").one()
        self.assertEqual(tag.objects, [family2])

        # then both
        sleep(0.02)
        untag_objects("test", [family1, family2])

        # get object by tag
        tag = self.session.query(Tag).filter_by(tag="test").one()
        self.assertEqual(tag.objects, [])
