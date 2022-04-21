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
import sqlite3 as sqlite

from roundup.backends import get_backend, have_backend

from .db_test_base import DBTest, ROTest, SchemaTest, ClassicInitTest, config
from .db_test_base import ConcurrentDBTest, FilterCacheTest
from .db_test_base import SpecialActionTest
from .rest_common  import TestCase as RestTestCase

class sqliteOpener:
    if have_backend('sqlite'):
        module = get_backend('sqlite')

    def nuke_database(self):
        shutil.rmtree(config.DATABASE)


class sqliteDBTest(sqliteOpener, DBTest, unittest.TestCase):

    def testUpgrade_6_to_7(self):

        # load the database
        self.db.issue.create(title="flebble frooz")
        self.db.commit()

        if self.db.database_schema['version'] != 7:
            self.skipTest("This test only runs for database version 7")

        self.db.database_schema['version'] = 6

        # dropping _fts
        #  select * from _fts
        #    it should fail.
        # run post-init
        #    same select should succeed (with no rows returned)

        self.db.sql("drop table __fts")

        with self.assertRaises(sqlite.OperationalError) as ctx:
            self.db.sql("select * from __fts")

        self.assertIn("no such table: __fts", ctx.exception.args[0])

        if hasattr(self, "downgrade_only"):
            return

        # test upgrade adding __fts table
        self.db.post_init()

        # select should now work.
        self.db.sql("select * from __fts")

        # we should be at the current db version
        self.assertEqual(self.db.database_schema['version'],
                         self.db.current_db_version)

class sqliteROTest(sqliteOpener, ROTest, unittest.TestCase):
    pass


class sqliteSchemaTest(sqliteOpener, SchemaTest, unittest.TestCase):
    pass


class sqliteClassicInitTest(ClassicInitTest, unittest.TestCase):
    backend = 'sqlite'


class sqliteConcurrencyTest(ConcurrentDBTest, unittest.TestCase):
    backend = 'sqlite'


class sqliteFilterCacheTest(sqliteOpener, FilterCacheTest, unittest.TestCase):
    backend = 'sqlite'

class sqliteSpecialActionTestCase(sqliteOpener, SpecialActionTest,
                                  unittest.TestCase):
    backend = 'sqlite'


from .session_common import SessionTest
class sqliteSessionTest(sqliteOpener, SessionTest, unittest.TestCase):
    pass

class sqliteRestTest (RestTestCase, unittest.TestCase):
    backend = 'sqlite'
