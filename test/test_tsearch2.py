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
# $Id: test_tsearch2.py,v 1.1 2004-12-16 22:22:55 jlgijsbers Exp $

import unittest

from roundup.hyperdb import DatabaseError

from db_test_base import DBTest, ROTest, config, SchemaTest, ClassicInitTest

from roundup.backends import get_backend, have_backend

class tsearch2Opener:
    if have_backend('tsearch2'):
        module = get_backend('tsearch2')

    def setUp(self):
        pass

    def tearDown(self):
        self.nuke_database()

    def nuke_database(self):
        # clear out the database - easiest way is to nuke and re-create it
        self.module.db_nuke(config)

class tsearch2DBTest(tsearch2Opener, DBTest):
    def setUp(self):
        tsearch2Opener.setUp(self)
        DBTest.setUp(self)

    def tearDown(self):
        DBTest.tearDown(self)
        tsearch2Opener.tearDown(self)

    def testFilteringIntervalSort(self):
        # Tsearch2 sorts NULLs differently to other databases (others
        # treat it as lower than real values, PG treats it as higher)
        ae, filt = self.filteringSetup()
        # ascending should sort None, 1:10, 1d
        ae(filt(None, {}, ('+','foo'), (None,None)), ['4', '1', '2', '3'])
        # descending should sort 1d, 1:10, None
        ae(filt(None, {}, ('-','foo'), (None,None)), ['3', '2', '1', '4'])

    def testTransactions(self):
        # XXX: in its current form, this test doesn't make sense for tsearch2.
        # It tests the transactions mechanism by counting the number of files
        # in the FileStorage. As tsearch2 doesn't use the FileStorage, this
        # fails. The test should probably be rewritten with some other way of
        # checking rollbacks/commits.
        pass

class tsearch2ROTest(tsearch2Opener, ROTest):
    def setUp(self):
        tsearch2Opener.setUp(self)
        ROTest.setUp(self)

    def tearDown(self):
        ROTest.tearDown(self)
        tsearch2Opener.tearDown(self)

class tsearch2SchemaTest(tsearch2Opener, SchemaTest):
    def setUp(self):
        tsearch2Opener.setUp(self)
        SchemaTest.setUp(self)

    def tearDown(self):
        SchemaTest.tearDown(self)
        tsearch2Opener.tearDown(self)

class tsearch2ClassicInitTest(tsearch2Opener, ClassicInitTest):
    backend = 'tsearch2'
    def setUp(self):
        tsearch2Opener.setUp(self)
        ClassicInitTest.setUp(self)

    def tearDown(self):
        ClassicInitTest.tearDown(self)
        tsearch2Opener.tearDown(self)

from session_common import RDBMSTest
class tsearch2SessionTest(tsearch2Opener, RDBMSTest):
    def setUp(self):
        tsearch2Opener.setUp(self)
        RDBMSTest.setUp(self)
    def tearDown(self):
        RDBMSTest.tearDown(self)
        tsearch2Opener.tearDown(self)

def test_suite():
    suite = unittest.TestSuite()
    if not have_backend('tsearch2'):
        print "Skipping tsearch2 tests"
        return suite

    # make sure we start with a clean slate
    if tsearch2Opener.module.db_exists(config):
        tsearch2Opener.module.db_nuke(config, 1)

    # TODO: Check if we can run postgresql tests
    print 'Including tsearch2 tests'
    suite.addTest(unittest.makeSuite(tsearch2DBTest))
    suite.addTest(unittest.makeSuite(tsearch2ROTest))
    suite.addTest(unittest.makeSuite(tsearch2SchemaTest))
    suite.addTest(unittest.makeSuite(tsearch2ClassicInitTest))
    suite.addTest(unittest.makeSuite(tsearch2SessionTest))
    return suite

# vim: set et sts=4 sw=4 :
