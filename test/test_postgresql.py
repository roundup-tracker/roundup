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
# $Id: test_postgresql.py,v 1.3 2003-11-11 11:19:18 richard Exp $ 

import sys, unittest, os, shutil, time, popen2

from roundup.hyperdb import DatabaseError

from db_test_base import DBTest, ROTest, config, SchemaTest, ClassicInitTest

# Postgresql connection data
# NOTE: THIS MUST BE A LOCAL DATABASE
config.POSTGRESQL_DATABASE = {'database': 'rounduptest'}

from roundup import backends

def db_create():
    """Clear all database contents and drop database itself"""
    name = config.POSTGRESQL_DATABASE['database']
    cout,cin = popen2.popen4('createdb %s'%name)
    cin.close()
    response = cout.read().split('\n')[0]
    if response.find('FATAL') != -1 or response.find('ERROR') != -1:
        raise RuntimeError, response

def db_nuke(fail_ok=0):
    """Clear all database contents and drop database itself"""
    name = config.POSTGRESQL_DATABASE['database']
    cout,cin = popen2.popen4('dropdb %s'%name)
    cin.close()
    response = cout.read().split('\n')[0]
    if response.endswith('does not exist') and fail_ok:
        return
    if response.find('FATAL') != -1 or response.find('ERROR') != -1:
        raise RuntimeError, response
    if os.path.exists(config.DATABASE):
        shutil.rmtree(config.DATABASE)

def db_exists(config):
    """Check if database already exists"""
    try:
        db = Database(config, 'admin')
        return 1
    except:
        return 0

class postgresqlOpener:
    if hasattr(backends, 'postgresql'):
        from roundup.backends import postgresql as module

    def setUp(self):
        db_nuke(1)
        db_create()

    def tearDown(self):
        db_nuke()

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
    extra_config = "POSTGRESQL_DATABASE = {'database': 'rounduptest'}"
    def setUp(self):
        postgresqlOpener.setUp(self)
        ClassicInitTest.setUp(self)

    def tearDown(self):
        ClassicInitTest.tearDown(self)
        postgresqlOpener.tearDown(self)

def test_suite():
    suite = unittest.TestSuite()
    if not hasattr(backends, 'postgresql'):
        return suite

    # Check if we can run postgresql tests
    print 'Including postgresql tests'
    suite.addTest(unittest.makeSuite(postgresqlDBTest))
    suite.addTest(unittest.makeSuite(postgresqlROTest))
    suite.addTest(unittest.makeSuite(postgresqlSchemaTest))
    suite.addTest(unittest.makeSuite(postgresqlClassicInitTest))
    return suite

