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

import unittest

import pytest
from roundup.hyperdb import DatabaseError
from roundup.backends import get_backend, have_backend
from roundup.backends.back_postgresql import db_command, db_schema_split

from .db_test_base import DBTest, ROTest, config, SchemaTest, ClassicInitTest
from .db_test_base import ConcurrentDBTest, HTMLItemTest, FilterCacheTest
from .db_test_base import ClassicInitBase, setupTracker, SpecialActionTest
from .rest_common import TestCase as RestTestCase

if not have_backend('postgresql'):
    # FIX: workaround for a bug in pytest.mark.skip():
    #   https://github.com/pytest-dev/pytest/issues/568
    from .pytest_patcher import mark_class
    skip_postgresql = mark_class(pytest.mark.skip(
        reason='Skipping PostgreSQL tests: backend not available'))
else:
    try:
        from roundup.backends.back_postgresql import psycopg2, db_command
        db_command(config, 'select 1')
        skip_postgresql = lambda func, *args, **kwargs: func
    except( DatabaseError ) as msg:
        from .pytest_patcher import mark_class
        skip_postgresql = mark_class(pytest.mark.skip(
            reason='Skipping PostgreSQL tests: database not available'))

@skip_postgresql
class postgresqlOpener:
    if have_backend('postgresql'):
        module = get_backend('postgresql')

    def setup_class(cls):
        # nuke the db once for the class. Handles the case
        # where an aborted test run (^C during setUp for example)
        # leaves the database in an unusable, partly configured state.
        try:
            cls.nuke_database()
        except Exception as m:
            # ignore failure to nuke the database if it doesn't exist.
            # otherwise abort
            if str(m.args[0]) == (
                    'database "%s" does not exist' % config.RDBMS_NAME):
                pass
            else:
                raise

    def setUp(self):
        pass

    def tearDown(self):
        self.nuke_database()

    @classmethod
    def nuke_database(self):
        # clear out the database - easiest way is to nuke and re-create it
        self.module.db_nuke(config)

@skip_postgresql
class postgresqlSchemaOpener:

    RDBMS_NAME="rounduptest_schema.rounduptest"
    RDBMS_USER="rounduptest_schema"
        
    if have_backend('postgresql'):
        module = get_backend('postgresql')

    def setup_class(cls):
        # nuke the schema for the class. Handles the case
        # where an aborted test run (^C during setUp for example)
        # leaves the database in an unusable, partly configured state.
        config.RDBMS_NAME=cls.RDBMS_NAME
        config.RDBMS_USER=cls.RDBMS_USER

        database, schema = db_schema_split(config.RDBMS_NAME)

        try:
            cls.nuke_database()
        except Exception as m:
            # ignore failure to nuke the database if it doesn't exist.
            # otherwise abort
            if str(m.args[0]) == (
                    'schema "%s" does not exist' % schema):
                pass
            else:
                raise

    def setUp(self):
        # make sure to override the rdbms settings.
        # before every test.
        config.RDBMS_NAME=self.RDBMS_NAME
        config.RDBMS_USER=self.RDBMS_USER

    def tearDown(self):
        self.nuke_database()
        config.RDBMS_NAME="rounduptest"
        config.RDBMS_USER="rounduptest"

    @classmethod
    def nuke_database(self):
        # clear out the database - easiest way is to nuke and re-create it
        self.module.db_nuke(config)

@skip_postgresql
class postgresqlPrecreatedSchemaDbOpener:
    """Open the db where the user has only schema create rights.
       The test tries to nuke the db and should result in an exception.

       RDBMS_NAME should not have the .schema on it as we want to
       operate on the db itself with db_nuke.
    """

    RDBMS_NAME="rounduptest_schema"
    RDBMS_USER="rounduptest_schema"
        
    if have_backend('postgresql'):
        module = get_backend('postgresql')

    def setup_class(cls):
        # nuke the schema for the class. Handles the case
        # where an aborted test run (^C during setUp for example)
        # leaves the database in an unusable, partly configured state.
        config.RDBMS_NAME=cls.RDBMS_NAME
        config.RDBMS_USER=cls.RDBMS_USER

    def setUp(self):
        # make sure to override the rdbms settings.
        # before every test.
        config.RDBMS_NAME=self.RDBMS_NAME
        config.RDBMS_USER=self.RDBMS_USER

    def tearDown(self):
        config.RDBMS_NAME="rounduptest"
        config.RDBMS_USER="rounduptest"

    @classmethod
    def nuke_database(self):
        # clear out the database - easiest way is to nuke and re-create it
        self.module.db_nuke(config)

@skip_postgresql
class postgresqlAdditionalDBTest():
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

        # remove __fts table/index; shrink length of  __words._words
        #  trying to insert a long word in __words._words should fail.
        #  trying to select from __fts should fail
        #  looking for the index should fail
        # run post-init
        #    tests should succeed.

        self.db.sql("drop table __fts")  # also drops __fts_idx
        self.db.sql("alter table __words ALTER column _word type varchar(10)")
        self.db.commit()

        self.db.database_schema['version'] = 6

        long_string = "a" * (self.db.indexer.maxlength + 5)
        with self.assertRaises(psycopg2.DataError) as ctx:
            # DataError : value too long for type character varying(10)
            self.db.sql("insert into __words VALUES('%s',1)" % long_string)

        self.assertIn("varying(10)", ctx.exception.args[0])
        self.db.rollback()  # clear cursor error so db.sql can be used again

        with self.assertRaises(psycopg2.errors.UndefinedTable) as ctx:
            self.db.sql("select * from _fts")
        self.db.rollback()

        self.assertFalse(self.db.sql_index_exists('__fts', '__fts_idx'))

        if hasattr(self, "downgrade_only"):
            return

        # test upgrade path
        self.db.post_init()

        self.assertEqual(self.db.db_version_updated, True)

        # This insert with text of expected column size should succeed
        self.db.sql("insert into __words VALUES('%s',1)" % long_string)

        # verify it fails at one more than the expected column size
        too_long_string = "a" * (self.db.indexer.maxlength + 6)
        with self.assertRaises(psycopg2.DataError) as ctx:
            self.db.sql("insert into __words VALUES('%s',1)" % too_long_string)

        # clean db handle
        self.db.rollback()

        self.assertTrue(self.db.sql_index_exists('__fts', '__fts_idx'))

        self.db.sql("select * from __fts")

        self.assertEqual(self.db.database_schema['version'],
                         self.db.current_db_version)

    def testUpgrade_7_to_8(self):
        """ change _time fields in BasicDatabases to double """
        # load the database
        self.db.issue.create(title="flebble frooz")
        self.db.commit()

        if self.db.database_schema['version'] != 8:
            self.skipTest("This test only runs for database version 8")

        # change otk and session db's _time value to their original types
        sql = "alter table sessions alter column session_time type REAL;"
        self.db.sql(sql)
        sql = "alter table otks alter column otk_time type REAL;"
        self.db.sql(sql)

        # verify they truncate long ints.
        test_double =  1658718284.7616878
        for tablename in ['otk', 'session']:
            self.db.sql(
              'insert into %(name)ss(%(name)s_key, %(name)s_time, %(name)s_value) '
              "values ('foo', %(double)s, 'value');"%{'name': tablename,
                                                     'double': test_double}
            )

            self.db.cursor.execute('select %(name)s_time from %(name)ss '
                            "where %(name)s_key = 'foo'"%{'name': tablename})

            self.assertNotAlmostEqual(self.db.cursor.fetchone()[0],
                                      test_double, -1)

            # cleanup or else the inserts after the upgrade will not
            # work.
            self.db.sql("delete from %(name)ss where %(name)s_key='foo'"%{
                'name': tablename} )

        self.db.database_schema['version'] = 7

        if hasattr(self,"downgrade_only"):
            return

        # test upgrade altering row
        self.db.post_init()

        self.assertEqual(self.db.db_version_updated, True)

        # verify they keep all signifcant digits before the decimal point
        for tablename in ['otk', 'session']:
            self.db.sql(
              'insert into %(name)ss(%(name)s_key, %(name)s_time, %(name)s_value) '
              "values ('foo', %(double)s, 'value');"%{'name': tablename,
                                                     'double': test_double}
            )

            self.db.cursor.execute('select %(name)s_time from %(name)ss '
                            "where %(name)s_key = 'foo'"%{'name': tablename})

            self.assertAlmostEqual(self.db.cursor.fetchone()[0],
                                      test_double, -1)

        self.assertEqual(self.db.database_schema['version'], 8)

@skip_postgresql
class postgresqlDBTest(postgresqlOpener, DBTest,
                       postgresqlAdditionalDBTest, unittest.TestCase):
    def setUp(self):
        # set for manual integration testing of 'native-fts'
        # It is unset in tearDown so it doesn't leak into other tests.
        #  FIXME extract test methods in DBTest that hit the indexer
        #    into a new class (DBTestIndexer). Add DBTestIndexer
        #    to this class.
        #    Then create a new class in this file:
        #        postgresqlDBTestIndexerNative_FTS
        #    that imports from DBestIndexer to test native-fts.
        # config['INDEXER'] = 'native-fts'
        postgresqlOpener.setUp(self)
        DBTest.setUp(self)

    def tearDown(self):
        # clean up config to prevent leak if native-fts is tested
        config['INDEXER'] = ''
        DBTest.tearDown(self)
        postgresqlOpener.tearDown(self)

@skip_postgresql
@pytest.mark.pg_schema
class postgresqlDBTestSchema(postgresqlSchemaOpener, DBTest,
                             postgresqlAdditionalDBTest, unittest.TestCase):
    def setUp(self):
        # set for manual integration testing of 'native-fts'
        # It is unset in tearDown so it doesn't leak into other tests.
        #  FIXME extract test methods in DBTest that hit the indexer
        #    into a new class (DBTestIndexer). Add DBTestIndexer
        #    to this class.
        #    Then create a new class in this file:
        #        postgresqlDBTestIndexerNative_FTS
        #    that imports from DBestIndexer to test native-fts.
        # config['INDEXER'] = 'native-fts'
        postgresqlSchemaOpener.setUp(self)
        DBTest.setUp(self)

    def tearDown(self):
        # clean up config to prevent leak if native-fts is tested
        config['INDEXER'] = ''
        DBTest.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)


@skip_postgresql
class postgresqlROTest(postgresqlOpener, ROTest, unittest.TestCase):
    def setUp(self):
        postgresqlOpener.setUp(self)
        ROTest.setUp(self)

    def tearDown(self):
        ROTest.tearDown(self)
        postgresqlOpener.tearDown(self)

@skip_postgresql
@pytest.mark.pg_schema
class postgresqlROTestSchema(postgresqlSchemaOpener, ROTest,
                             unittest.TestCase):
    def setUp(self):
        postgresqlSchemaOpener.setUp(self)
        ROTest.setUp(self)

    def tearDown(self):
        ROTest.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)


@skip_postgresql
class postgresqlConcurrencyTest(postgresqlOpener, ConcurrentDBTest,
                                unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        ConcurrentDBTest.setUp(self)

    def tearDown(self):
        ConcurrentDBTest.tearDown(self)
        postgresqlOpener.tearDown(self)

@skip_postgresql
@pytest.mark.pg_schema
class postgresqlConcurrencyTestSchema(postgresqlSchemaOpener, ConcurrentDBTest,
                                      unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlSchemaOpener.setUp(self)
        ConcurrentDBTest.setUp(self)

    def tearDown(self):
        ConcurrentDBTest.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)



@skip_postgresql
class postgresqlAdditionalJournalTest():

    def _test_journal(self, expected_journal):
        id  = self.id
        db1 = self.db1 = self.tracker.open('admin')
        db2 = self.db2 = self.tracker.open('admin')

        t1  = db1.issue.get(id, 'title')
        t2  = db2.issue.get(id, 'title')

        db1.issue.set (id, title='t1')
        db1.commit()
        db1.close()

        # Test testConcurrentRepeatableRead is expected to raise
        # an error when the db2.issue.set() call is executed. 
        try:
            db2.issue.set (id, title='t2')
            db2.commit()    
        finally:
            # Make sure that the db2 connection is closed, even when
            # an error is raised.
            db2.close()
        self.db = self.tracker.open('admin')
        journal = self.db.getjournal('issue', id)
        for n, line in enumerate(journal):
            self.assertEqual(line[4], expected_journal[n])

    def testConcurrentReadCommitted(self):
        expected_journal = [
            {}, {'title': 'initial value'}, {'title': 'initial value'}
        ]
        self._test_journal(expected_journal)

    def testConcurrentRepeatableRead(self):
        self.tracker.config.RDBMS_ISOLATION_LEVEL='repeatable read'
        exc = self.module.TransactionRollbackError
        self.assertRaises(exc, self._test_journal, [])

@skip_postgresql
class postgresqlJournalTest(postgresqlOpener, ClassicInitBase,
                            postgresqlAdditionalJournalTest,
                            unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        ClassicInitBase.setUp(self)
        self.tracker = setupTracker(self.dirname, self.backend)
        db = self.tracker.open('admin')
        self.id = db.issue.create(title='initial value')
        db.commit()
        db.close()

    def tearDown(self):
        try:
            self.db1.close()
            self.db2.close()
        except psycopg2.InterfaceError as exc:
            if 'connection already closed' in str(exc): pass
            else: raise
        ClassicInitBase.tearDown(self)
        postgresqlOpener.tearDown(self)


@skip_postgresql
@pytest.mark.pg_schema
class postgresqlJournalTestSchema(postgresqlSchemaOpener, ClassicInitBase,
                                  postgresqlAdditionalJournalTest,
                                  unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlSchemaOpener.setUp(self)
        ClassicInitBase.setUp(self)
        self.tracker = setupTracker(self.dirname, self.backend)
        db = self.tracker.open('admin')
        self.id = db.issue.create(title='initial value')
        db.commit()
        db.close()

    def tearDown(self):
        try:
            self.db1.close()
            self.db2.close()
        except psycopg2.InterfaceError as exc:
            if 'connection already closed' in str(exc): pass
            else: raise
        ClassicInitBase.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)


@skip_postgresql
class postgresqlHTMLItemTest(postgresqlOpener, HTMLItemTest,
                             unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        HTMLItemTest.setUp(self)

    def tearDown(self):
        HTMLItemTest.tearDown(self)
        postgresqlOpener.tearDown(self)


@skip_postgresql
@pytest.mark.pg_schema
class postgresqlHTMLItemTestSchema(postgresqlSchemaOpener, HTMLItemTest,
                             unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlSchemaOpener.setUp(self)
        HTMLItemTest.setUp(self)

    def tearDown(self):
        HTMLItemTest.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)


@skip_postgresql
class postgresqlFilterCacheTest(postgresqlOpener, FilterCacheTest,
                                unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        FilterCacheTest.setUp(self)

    def tearDown(self):
        FilterCacheTest.tearDown(self)
        postgresqlOpener.tearDown(self)

@skip_postgresql
@pytest.mark.pg_schema
class postgresqlFilterCacheTestSchema(postgresqlSchemaOpener, FilterCacheTest,
                                unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlSchemaOpener.setUp(self)
        FilterCacheTest.setUp(self)

    def tearDown(self):
        FilterCacheTest.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)


@skip_postgresql
class postgresqlSchemaTest(postgresqlOpener, SchemaTest, unittest.TestCase):
    def setUp(self):
        postgresqlOpener.setUp(self)
        SchemaTest.setUp(self)

    def tearDown(self):
        SchemaTest.tearDown(self)
        postgresqlOpener.tearDown(self)


@skip_postgresql
@pytest.mark.pg_schema
class postgresqlSchemaTestSchema(postgresqlSchemaOpener, SchemaTest,
                                 unittest.TestCase):
    def setUp(self):
        postgresqlSchemaOpener.setUp(self)
        SchemaTest.setUp(self)

    def tearDown(self):
        SchemaTest.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)


@skip_postgresql
class postgresqlClassicInitTest(postgresqlOpener, ClassicInitTest,
                                unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        ClassicInitTest.setUp(self)

    def tearDown(self):
        ClassicInitTest.tearDown(self)
        postgresqlOpener.tearDown(self)


@skip_postgresql
@pytest.mark.pg_schema
class postgresqlClassicInitTestSchema(postgresqlSchemaOpener, ClassicInitTest,
                                      unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlSchemaOpener.setUp(self)
        ClassicInitTest.setUp(self)

    def tearDown(self):
        ClassicInitTest.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)


from .session_common import SessionTest
@skip_postgresql
class postgresqlSessionTest(postgresqlOpener, SessionTest, unittest.TestCase):
    s2b = lambda x,y : y

    def setUp(self):
        postgresqlOpener.setUp(self)
        SessionTest.setUp(self)
    def tearDown(self):
        SessionTest.tearDown(self)
        postgresqlOpener.tearDown(self)


@skip_postgresql
@pytest.mark.pg_schema
class postgresqlSessionTestSchema(postgresqlSchemaOpener, SessionTest,
                                  unittest.TestCase):
    s2b = lambda x,y : y

    def setUp(self):
        postgresqlSchemaOpener.setUp(self)
        SessionTest.setUp(self)
    def tearDown(self):
        SessionTest.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)


@skip_postgresql
class postgresqlSpecialActionTestCase(postgresqlOpener, SpecialActionTest,
                             unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        SpecialActionTest.setUp(self)

    def tearDown(self):
        SpecialActionTest.tearDown(self)
        postgresqlOpener.tearDown(self)

@skip_postgresql
@pytest.mark.pg_schema
class postgresqlSpecialActionTestCaseSchema(postgresqlSchemaOpener,
                                            SpecialActionTest,
                                            unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlSchemaOpener.setUp(self)
        SpecialActionTest.setUp(self)

    def tearDown(self):
        SpecialActionTest.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)

@skip_postgresql
class postgresqlRestTest (postgresqlOpener, RestTestCase, unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        RestTestCase.setUp(self)

    def tearDown(self):
        RestTestCase.tearDown(self)
        postgresqlOpener.tearDown(self)


@skip_postgresql
@pytest.mark.pg_schema
class postgresqlRestTestSchema(postgresqlSchemaOpener, RestTestCase,
                          unittest.TestCase):
    backend = 'postgresql'
    def setUp(self):
        postgresqlSchemaOpener.setUp(self)
        RestTestCase.setUp(self)

    def tearDown(self):
        RestTestCase.tearDown(self)
        postgresqlSchemaOpener.tearDown(self)


@skip_postgresql
@pytest.mark.pg_schema
class postgresqlDbDropFailureTestSchema(postgresqlPrecreatedSchemaDbOpener,
                               unittest.TestCase):

    def test_drop(self):
        """Verify that the schema test database can not be dropped."""

        with self.assertRaises(RuntimeError) as m:
            self.module.db_nuke(config)


        self.assertEqual(m.exception.args[0],
                         'must be owner of database rounduptest_schema')



# vim: set et sts=4 sw=4 :
