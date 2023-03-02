#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.

import unittest, os, shutil, time

import pytest
from roundup.hyperdb import DatabaseError
from roundup.backends import get_backend, have_backend

from .db_test_base import DBTest, ROTest, config, SchemaTest, ClassicInitTest
from .db_test_base import ConcurrentDBTest, HTMLItemTest, FilterCacheTest
from .db_test_base import SpecialActionTest
from .rest_common import TestCase as RestTestCase


class mysqlOpener:
    if have_backend('mysql'):
        module = get_backend('mysql')

    def setUp(self):
        self.module.db_nuke(config)

    def tearDown(self):
        self.db.close()
        self.nuke_database()

    def nuke_database(self):
        self.module.db_nuke(config)


# FIX: workaround for a bug in pytest.mark.skip():
#   https://github.com/pytest-dev/pytest/issues/568
from .pytest_patcher import mark_class

if not have_backend('mysql'):
    skip_mysql = mark_class(pytest.mark.skip(
        reason='Skipping MySQL tests: backend not available'))
else:
    try:
        import MySQLdb
        mysqlOpener.module.db_exists(config)
        skip_mysql = lambda func, *args, **kwargs: func
    except (MySQLdb.MySQLError, DatabaseError) as msg:
        skip_mysql = mark_class(pytest.mark.skip(
            reason='Skipping MySQL tests: %s' % str(msg)))


@skip_mysql
class mysqlDBTest(mysqlOpener, DBTest, unittest.TestCase):
    def setUp(self):
        mysqlOpener.setUp(self)
        DBTest.setUp(self)

    def testUpgrade_6_to_7(self):

        # load the database
        self.db.issue.create(title="flebble frooz")
        self.db.commit()

        if self.db.database_schema['version'] > 7:
            # make testUpgrades run the downgrade code only.
            if hasattr(self, "downgrade_only"):
                # we are being called by an earlier test
                self.testUpgrade_7_to_8()
                self.assertEqual(self.db.database_schema['version'], 7)
            else:
                # we are being called directly
                self.downgrade_only = True
                self.testUpgrade_7_to_8()
                self.assertEqual(self.db.database_schema['version'], 7)
                del(self.downgrade_only)
        elif self.db.database_schema['version'] != 7:
            self.skipTest("This test only runs for database version 7")


        # test by shrinking _words and trying to insert a long value
        #    it should fail.
        # run post-init
        #    same test should succeed.

        self.db.sql("alter table __words change column "
                    "_word _word varchar(10)")

        long_string = "a" * (self.db.indexer.maxlength + 5)

        with self.assertRaises(MySQLdb.DataError) as ctx:
            # DataError : Data too long for column '_word' at row 1
            self.db.sql("insert into __words VALUES('%s',1)" % long_string)

        self.assertIn("Data too long for column '_word'",
                      ctx.exception.args[1])

        self.db.database_schema['version'] = 6

        if hasattr(self,"downgrade_only"):
            return

        # test upgrade altering row
        self.db.post_init()

        self.assertEqual(self.db.db_version_updated, True)

        # This insert with text of expected column size should succeed
        self.db.sql("insert into __words VALUES('%s',1)" % long_string)

        # Verify it fails at one more than the expected column size
        too_long_string = "a" * (self.db.indexer.maxlength + 6)
        with self.assertRaises(MySQLdb.DataError) as ctx:
            self.db.sql("insert into __words VALUES('%s',1)" % too_long_string)

        self.assertEqual(self.db.database_schema['version'],
                         self.db.current_db_version)

    def testUpgrade_7_to_8(self):
        # load the database
        self.db.issue.create(title="flebble frooz")
        self.db.commit()

        if self.db.database_schema['version'] != 8:
            self.skipTest("This test only runs for database version 8")

        # change otk and session db's _time value to their original types
        sql = "alter table sessions modify session_time float;"
        self.db.sql(sql)
        sql = "alter table otks modify otk_time float;"
        self.db.sql(sql)

        # verify they truncate long ints.
        test_double =  1658718284.7616878
        for tablename in ['otk', 'session']:
            self.db.sql(
              'insert %(name)ss(%(name)s_key, %(name)s_time, %(name)s_value) '
              'values("foo", %(double)s, "value");'%{'name': tablename,
                                                     'double': test_double}
            )

            self.db.cursor.execute('select %(name)s_time from %(name)ss '
                            'where %(name)s_key = "foo"'%{'name': tablename})

            self.assertNotAlmostEqual(self.db.cursor.fetchone()[0],
                                      test_double, -1)

            # cleanup or else the inserts after the upgrade will not
            # work.
            self.db.sql("delete from %(name)ss where %(name)s_key='foo'"%{
                'name': tablename} )

        self.db.database_schema['version'] = 7

        if hasattr(self,"downgrade_only"):
            return

        # test upgrade
        self.db.post_init()

        self.assertEqual(self.db.db_version_updated, True)

        # verify they keep all signifcant digits before the decimal point
        for tablename in ['otk', 'session']:
            self.db.sql(
              'insert %(name)ss(%(name)s_key, %(name)s_time, %(name)s_value) '
              'values("foo", %(double)s, "value");'%{'name': tablename,
                                                     'double': test_double}
            )

            self.db.cursor.execute('select %(name)s_time from %(name)ss '
                            'where %(name)s_key = "foo"'%{'name': tablename})

            # -1 compares just the integer part. No fractions.
            self.assertAlmostEqual(self.db.cursor.fetchone()[0],
                                  test_double, -1)

        self.assertEqual(self.db.database_schema['version'], 8)

@skip_mysql
class mysqlROTest(mysqlOpener, ROTest, unittest.TestCase):
    def setUp(self):
        mysqlOpener.setUp(self)
        ROTest.setUp(self)


@skip_mysql
class mysqlSchemaTest(mysqlOpener, SchemaTest, unittest.TestCase):
    def setUp(self):
        mysqlOpener.setUp(self)
        SchemaTest.setUp(self)


@skip_mysql
class mysqlClassicInitTest(mysqlOpener, ClassicInitTest, unittest.TestCase):
    backend = 'mysql'
    def setUp(self):
        mysqlOpener.setUp(self)
        ClassicInitTest.setUp(self)
    def tearDown(self):
        ClassicInitTest.tearDown(self)
        self.nuke_database()


@skip_mysql
class mysqlConcurrencyTest(mysqlOpener, ConcurrentDBTest, unittest.TestCase):
    backend = 'mysql'
    def setUp(self):
        mysqlOpener.setUp(self)
        ConcurrentDBTest.setUp(self)
    def tearDown(self):
        ConcurrentDBTest.tearDown(self)
        self.nuke_database()


@skip_mysql
class mysqlHTMLItemTest(mysqlOpener, HTMLItemTest, unittest.TestCase):
    backend = 'mysql'
    def setUp(self):
        mysqlOpener.setUp(self)
        HTMLItemTest.setUp(self)
    def tearDown(self):
        HTMLItemTest.tearDown(self)
        self.nuke_database()


@skip_mysql
class mysqlFilterCacheTest(mysqlOpener, FilterCacheTest, unittest.TestCase):
    backend = 'mysql'
    def setUp(self):
        mysqlOpener.setUp(self)
        FilterCacheTest.setUp(self)
    def tearDown(self):
        FilterCacheTest.tearDown(self)
        self.nuke_database()


from .session_common import SessionTest
@skip_mysql
class mysqlSessionTest(mysqlOpener, SessionTest, unittest.TestCase):
    s2b = lambda x,y : y

    def setUp(self):
        mysqlOpener.setUp(self)
        SessionTest.setUp(self)
    def tearDown(self):
        SessionTest.tearDown(self)
        mysqlOpener.tearDown(self)

@skip_mysql
class mysqlSpecialActionTestCase(mysqlOpener, SpecialActionTest,
                             unittest.TestCase):
    backend = 'mysql'
    def setUp(self):
        mysqlOpener.setUp(self)
        SpecialActionTest.setUp(self)

    def tearDown(self):
        SpecialActionTest.tearDown(self)
        mysqlOpener.tearDown(self)

@skip_mysql
class mysqlRestTest (RestTestCase, unittest.TestCase):
    backend = 'mysql'

# vim: set et sts=4 sw=4 :
