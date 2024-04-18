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
from roundup.backends.sessions_sqlite import Sessions, OneTimeKeys

from .db_test_base import DBTest, ROTest, SchemaTest, ClassicInitTest, config
from .db_test_base import ConcurrentDBTest, FilterCacheTest
from .db_test_base import SpecialActionTest
from .rest_common  import TestCase as RestTestCase

class sqliteOpener:
    if have_backend('sqlite'):
        module = get_backend('sqlite')

    def nuke_database(self):
        shutil.rmtree(config.DATABASE)

    def testWalMode(self):
        """verify that all sqlite db's are in WAL mode
           and not journal mode
        """
        if not hasattr(self, 'db'):
            self.skipTest("test has no database open")

        for db in [self.db]:
            print("testing db", str(db))
            db.sql('pragma journal_mode;')
            self.assertEqual(db.cursor.fetchone()['journal_mode'], 'wal')


class sqliteDBTest(sqliteOpener, DBTest, unittest.TestCase):

    def setUp(self):
        # set for manual integration testing of 'native-fts'
        # It is unset in tearDown so it doesn't leak into other tests.
        #  FIXME extract test methods in DBTest that hit the indexer
        #    into a new class (DBTestIndexer). Add DBTestIndexer
        #    to this class.
        #    Then create a new class in this file:
        #        sqliteDBTestIndexerNative_FTS
        #    that imports from DBestIndexer to test native-fts.
        #
        #config['INDEXER'] = 'native-fts'
        DBTest.setUp(self)

    def tearDown(self):
        # clean up config to prevent leak if native-fts is tested
        config['INDEXER'] = ''
        DBTest.tearDown(self)

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

        self.assertEqual(self.db.db_version_updated, True)

        # select should now work.
        self.db.sql("select * from __fts")

        # we should be at the current db version
        self.assertEqual(self.db.database_schema['version'],
                         self.db.current_db_version)

    def testUpgrade_7_to_8(self):
        # load the database
        self.db.issue.create(title="flebble frooz")
        self.db.commit()

        if self.db.database_schema['version'] != 8:
            self.skipTest("This test only runs for database version 8")

        # set up separate session/otk db's.
        self.db.Otk = OneTimeKeys(self.db)
        self.db.Session = Sessions(self.db)

        handle={}
        handle['otk'] = self.db.Otk
        handle['session'] = self.db.Session

        # verify they don't truncate long ints.
        test_double =  1658718284.7616878
        for tablename in ['otk', 'session']:
            Bdb = handle[tablename]
            Bdb.sql(
              'insert into %(name)ss(%(name)s_key, %(name)s_time, %(name)s_value) '
              'values("foo", %(double)s, "value");'%{'name': tablename,
                                                     'double': test_double}
            )

            Bdb.cursor.execute('select %(name)s_time from %(name)ss '
                            'where %(name)s_key = "foo"'%{'name': tablename})

            self.assertAlmostEqual(Bdb.cursor.fetchone()[0],
                                      test_double, -1)

            # cleanup or else the inserts after the upgrade will not
            # work.
            Bdb.sql("delete from %(name)ss where %(name)s_key='foo'"%{
                'name': tablename} )

        self.db.database_schema['version'] = 7

        if hasattr(self,"downgrade_only"):
            return

        # test upgrade altering row
        self.db.post_init()

        self.assertEqual(self.db.db_version_updated, True)

        # verify they keep all signifcant digits before the decimal point
        for tablename in ['otk', 'session']:
            Bdb = handle[tablename]
            Bdb.sql(
              'insert into %(name)ss(%(name)s_key, %(name)s_time, %(name)s_value) '
              'values("foo", %(double)s, "value");'%{'name': tablename,
                                                     'double': test_double}
            )

            Bdb.cursor.execute('select %(name)s_time from %(name)ss '
                            'where %(name)s_key = "foo"'%{'name': tablename})

            self.assertAlmostEqual(Bdb.cursor.fetchone()[0],
                                      test_double, -1)

        self.assertEqual(self.db.database_schema['version'], 8)


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
    s2b = lambda x,y : y

    def testDbType(self):
        self.assertIn("roundlite", repr(self.db))
        self.assertIn("roundup.backends.sessions_sqlite.Sessions", repr(self.db.Session))

    def testWalMode(self):
        """verify that all sqlite db's are in WAL mode
           and not Rollback mode
        """
        for db in [self.db, self.db.Session, self.db.Otk]:
            print("testing db", str(db))
            db.sql('pragma journal_mode;')
            self.assertEqual(db.cursor.fetchone()['journal_mode'], 'wal')

class anydbmSessionTest(sqliteOpener, SessionTest, unittest.TestCase):
    s2b = lambda x,y : y

    def setUp(self):
        SessionTest.setUp(self)

        # redefine the session db's as anydbm
        # close the existing session databases before opening new ones.
        self.db.Session.close()
        self.db.Otk.close()
        self.db.config.SESSIONDB_BACKEND = "anydbm"
        self.db.Session = None
        self.db.Otk = None
        self.sessions = self.db.getSessionManager()
        self.otks = self.db.getOTKManager()

    def tearDown(self):
        SessionTest.tearDown(self)

        # reset to default session backend
        self.db.config.SESSIONDB_BACKEND = ""
        self.db.Session = None
        self.db.Otk = None
        self.sessions = None
        self.otks = None

    def get_ts(self):
        return (self.sessions.get('random_session', '__timestamp'),)

    def testDbType(self):
        self.assertIn("roundlite", repr(self.db))
        self.assertIn("roundup.backends.sessions_dbm.Sessions", repr(self.db.Session))

  
class sqliteRestTest (RestTestCase, unittest.TestCase):
    backend = 'sqlite'
