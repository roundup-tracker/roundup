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
# 
# $Id: test_postgresql.py,v 1.10 2004-05-23 09:44:47 richard Exp $ 

import unittest

from roundup.hyperdb import DatabaseError

from db_test_base import DBTest, ROTest, config, SchemaTest, ClassicInitTest

# Postgresql connection data
# NOTE: THIS MUST BE A LOCAL DATABASE
config.POSTGRESQL_DATABASE = {'database': 'rounduptest'}

from roundup import backends

class postgresqlOpener:
    if hasattr(backends, 'postgresql'):
        from roundup.backends import postgresql as module

    def setUp(self):
        #from roundup.backends.back_postgresql import db_nuke
        #db_nuke(config, 1)
        pass

    def tearDown(self):
        self.nuke_database()

    def nuke_database(self):
        # clear out the database - easiest way is to nuke and re-create it
        from roundup.backends.back_postgresql import db_nuke
        db_nuke(config)

class postgresqlDBTest(postgresqlOpener, DBTest):
    def setUp(self):
        postgresqlOpener.setUp(self)
        DBTest.setUp(self)

    def tearDown(self):
        DBTest.tearDown(self)
        postgresqlOpener.tearDown(self)

    def testFilteringIntervalSort(self):
        # PostgreSQL sorts NULLs differently to other databases (others
        # treat it as lower than real values, PG treats it as higher)
        ae, filt = self.filteringSetup()
        # ascending should sort None, 1:10, 1d
        ae(filt(None, {}, ('+','foo'), (None,None)), ['4', '1', '2', '3'])
        # descending should sort 1d, 1:10, None
        ae(filt(None, {}, ('-','foo'), (None,None)), ['3', '2', '1', '4'])

class postgresqlROTest(postgresqlOpener, ROTest):
    def setUp(self):
        postgresqlOpener.setUp(self)
        ROTest.setUp(self)

    def tearDown(self):
        ROTest.tearDown(self)
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
    extra_config = "POSTGRESQL_DATABASE = %r"%config.POSTGRESQL_DATABASE
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
    if not hasattr(backends, 'postgresql'):
        print "Skipping postgresql tests"
        return suite

    # make sure we start with a clean slate
    from roundup.backends.back_postgresql import db_nuke, db_exists
    if db_exists(config):
        db_nuke(config, 1)

    # TODO: Check if we can run postgresql tests
    print 'Including postgresql tests'
    suite.addTest(unittest.makeSuite(postgresqlDBTest))
    suite.addTest(unittest.makeSuite(postgresqlROTest))
    suite.addTest(unittest.makeSuite(postgresqlSchemaTest))
    suite.addTest(unittest.makeSuite(postgresqlClassicInitTest))
    suite.addTest(unittest.makeSuite(postgresqlSessionTest))
    return suite

