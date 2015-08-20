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

from db_test_base import DBTest, ROTest, config, SchemaTest, ClassicInitTest
from db_test_base import ConcurrentDBTest, HTMLItemTest, FilterCacheTest
from db_test_base import ClassicInitBase, setupTracker

from roundup.backends import get_backend, have_backend

if not have_backend('postgresql'):
    SKIP_POSTGRESQL = True
else:
    SKIP_POSTGRESQL = False

skip_postgresql = pytest.mark.skipif(
    SKIP_POSTGRESQL, reason='Skipping PostgreSQL tests: not enabled')


class postgresqlOpener:
    if have_backend('postgresql'):
        module = get_backend('postgresql')

    def setUp(self):
        pass

    def tearDown(self):
        self.nuke_database()

    def nuke_database(self):
        # clear out the database - easiest way is to nuke and re-create it
        self.module.db_nuke(config)


@skip_postgresql
class postgresqlDBTest(postgresqlOpener, DBTest, unittest.TestCase):
    def setUp(self):
        postgresqlOpener.setUp(self)
        DBTest.setUp(self)

    def tearDown(self):
        DBTest.tearDown(self)
        postgresqlOpener.tearDown(self)


@skip_postgresql
class postgresqlROTest(postgresqlOpener, ROTest, unittest.TestCase):
    def setUp(self):
        postgresqlOpener.setUp(self)
        ROTest.setUp(self)

    def tearDown(self):
        ROTest.tearDown(self)
        postgresqlOpener.tearDown(self)


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
class postgresqlJournalTest(postgresqlOpener, ClassicInitBase,
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
        self.db1.close()
        self.db2.close()
        ClassicInitBase.tearDown(self)
        postgresqlOpener.tearDown(self)

    def _test_journal(self, expected_journal):
        id  = self.id
        db1 = self.db1 = self.tracker.open('admin')
        db2 = self.db2 = self.tracker.open('admin')

        t1  = db1.issue.get(id, 'title')
        t2  = db2.issue.get(id, 'title')

        db1.issue.set (id, title='t1')
        db1.commit()
        db1.close()

        db2.issue.set (id, title='t2')
        db2.commit()
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
class postgresqlSchemaTest(postgresqlOpener, SchemaTest, unittest.TestCase):
    def setUp(self):
        postgresqlOpener.setUp(self)
        SchemaTest.setUp(self)

    def tearDown(self):
        SchemaTest.tearDown(self)
        postgresqlOpener.tearDown(self)


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


from session_common import RDBMSTest
@skip_postgresql
class postgresqlSessionTest(postgresqlOpener, RDBMSTest, unittest.TestCase):
    def setUp(self):
        postgresqlOpener.setUp(self)
        RDBMSTest.setUp(self)
    def tearDown(self):
        RDBMSTest.tearDown(self)
        postgresqlOpener.tearDown(self)

def test_suite():
    suite = unittest.TestSuite()
    if not have_backend('postgresql'):
        print "Skipping postgresql tests"
        return suite

    # make sure we start with a clean slate
    if postgresqlOpener.module.db_exists(config):
        postgresqlOpener.module.db_nuke(config, 1)

    # TODO: Check if we can run postgresql tests
    print 'Including postgresql tests'
    suite.addTest(unittest.makeSuite(postgresqlDBTest))
    suite.addTest(unittest.makeSuite(postgresqlROTest))
    suite.addTest(unittest.makeSuite(postgresqlSchemaTest))
    suite.addTest(unittest.makeSuite(postgresqlClassicInitTest))
    suite.addTest(unittest.makeSuite(postgresqlSessionTest))
    suite.addTest(unittest.makeSuite(postgresqlConcurrencyTest))
    suite.addTest(unittest.makeSuite(postgresqlJournalTest))
    suite.addTest(unittest.makeSuite(postgresqlHTMLItemTest))
    suite.addTest(unittest.makeSuite(postgresqlFilterCacheTest))
    return suite

# vim: set et sts=4 sw=4 :
