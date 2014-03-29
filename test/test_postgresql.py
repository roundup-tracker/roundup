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

from roundup.hyperdb import DatabaseError

from db_test_base import DBTest, ROTest, config, SchemaTest, ClassicInitTest
from db_test_base import ConcurrentDBTest, HTMLItemTest, FilterCacheTest

from roundup.backends import get_backend, have_backend

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

class postgresqlDBTest(postgresqlOpener, DBTest):
    def setUp(self):
        postgresqlOpener.setUp(self)
        DBTest.setUp(self)

    def tearDown(self):
        DBTest.tearDown(self)
        postgresqlOpener.tearDown(self)

class postgresqlROTest(postgresqlOpener, ROTest):
    def setUp(self):
        postgresqlOpener.setUp(self)
        ROTest.setUp(self)

    def tearDown(self):
        ROTest.tearDown(self)
        postgresqlOpener.tearDown(self)

class postgresqlConcurrencyTest(postgresqlOpener, ConcurrentDBTest):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        ConcurrentDBTest.setUp(self)

    def tearDown(self):
        ConcurrentDBTest.tearDown(self)
        postgresqlOpener.tearDown(self)

class postgresqlHTMLItemTest(postgresqlOpener, HTMLItemTest):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        HTMLItemTest.setUp(self)

    def tearDown(self):
        HTMLItemTest.tearDown(self)
        postgresqlOpener.tearDown(self)

class postgresqlFilterCacheTest(postgresqlOpener, FilterCacheTest):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        FilterCacheTest.setUp(self)

    def tearDown(self):
        FilterCacheTest.tearDown(self)
        postgresqlOpener.tearDown(self)

class postgresqlSchemaTest(postgresqlOpener, SchemaTest):
    def setUp(self):
        postgresqlOpener.setUp(self)
        SchemaTest.setUp(self)

    def tearDown(self):
        SchemaTest.tearDown(self)
        postgresqlOpener.tearDown(self)

class postgresqlClassicInitTest(postgresqlOpener, ClassicInitTest):
    backend = 'postgresql'
    def setUp(self):
        postgresqlOpener.setUp(self)
        ClassicInitTest.setUp(self)

    def tearDown(self):
        ClassicInitTest.tearDown(self)
        postgresqlOpener.tearDown(self)

from session_common import RDBMSTest
class postgresqlSessionTest(postgresqlOpener, RDBMSTest):
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
    suite.addTest(unittest.makeSuite(postgresqlHTMLItemTest))
    suite.addTest(unittest.makeSuite(postgresqlFilterCacheTest))
    return suite

# vim: set et sts=4 sw=4 :
