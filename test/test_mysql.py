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

import unittest, os, shutil, time, imp

import pytest
from roundup.hyperdb import DatabaseError
from roundup.backends import get_backend, have_backend

from db_test_base import DBTest, ROTest, config, SchemaTest, ClassicInitTest
from db_test_base import ConcurrentDBTest, HTMLItemTest, FilterCacheTest


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


if not have_backend('mysql'):
    SKIP_MYSQL = True
    SKIP_MYSQL_REASON = 'Skipping MySQL tests: not enabled'
else:
    try:
        import MySQLdb
        mysqlOpener.module.db_exists(config)
        SKIP_MYSQL = False
        SKIP_MYSQL_REASON = ''
    except (MySQLdb.MySQLError, DatabaseError) as msg:
        SKIP_MYSQL = True
        SKIP_MYSQL_REASON = 'Skipping MySQL tests: %s' % str(msg)

skip_mysql = pytest.mark.skipif(SKIP_MYSQL, reason=SKIP_MYSQL_REASON)


@skip_mysql
class mysqlDBTest(mysqlOpener, DBTest, unittest.TestCase):
    def setUp(self):
        mysqlOpener.setUp(self)
        DBTest.setUp(self)


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


from session_common import RDBMSTest
@skip_mysql
class mysqlSessionTest(mysqlOpener, RDBMSTest, unittest.TestCase):
    def setUp(self):
        mysqlOpener.setUp(self)
        RDBMSTest.setUp(self)
    def tearDown(self):
        RDBMSTest.tearDown(self)
        mysqlOpener.tearDown(self)

def test_suite():
    suite = unittest.TestSuite()
    if not have_backend('mysql'):
        print "Skipping mysql tests"
        return suite

    import MySQLdb
    try:
        # Check if we can connect to the server.
        # use db_exists() to make a connection, ignore it's return value
        mysqlOpener.module.db_exists(config)
    except (MySQLdb.MySQLError, DatabaseError), msg:
        print "Skipping mysql tests (%s)"%msg
    else:
        print 'Including mysql tests'
        suite.addTest(unittest.makeSuite(mysqlDBTest))
        suite.addTest(unittest.makeSuite(mysqlROTest))
        suite.addTest(unittest.makeSuite(mysqlSchemaTest))
        suite.addTest(unittest.makeSuite(mysqlClassicInitTest))
        suite.addTest(unittest.makeSuite(mysqlSessionTest))
        suite.addTest(unittest.makeSuite(mysqlConcurrencyTest))
        suite.addTest(unittest.makeSuite(mysqlHTMLItemTest))
        suite.addTest(unittest.makeSuite(mysqlFilterCacheTest))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: set et sts=4 sw=4 :
