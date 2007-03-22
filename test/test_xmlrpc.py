#
# Copyright (C) 2007 Stefan Seefeld
# All rights reserved.
# Licensed to the public under the terms of the GNU LGPL (>= 2),
# see the file COPYING for details.
#

import unittest, os, shutil, errno, sys, difflib, cgi, re

from roundup.cgi.exceptions import *
from roundup import init, instance, password, hyperdb, date
from roundup.xmlrpc import RoundupServer

import db_test_base

NEEDS_INSTANCE = 1

class TestCaseBase(unittest.TestCase):

    def setUp(self):

        self.dirname = '_test_xmlrpc'
        # set up and open a tracker
        self.instance = db_test_base.setupTracker(self.dirname)

        # open the database
        self.db = self.instance.open('admin')
        self.db.user.create(username='joe', password=password.Password('random'),
                            address='random@home.org',
                            realname='Joe Random', roles='User')

        self.db.commit()
        self.db.close()
        
        self.server = RoundupServer(self.dirname)


    def tearDown(self):

        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

class AccessTestCase(TestCaseBase):

    def test(self):

        # Retrieve all three users.
        results = self.server.list('joe', 'random', 'user', 'id')
        self.assertEqual(len(results), 3)
        # Obtain data for 'joe'.
        userid = 'user' + results[-1]
        results = self.server.display('joe', 'random', userid)
        self.assertEqual(results['username'], 'joe')
        self.assertEqual(results['realname'], 'Joe Random')
        # Reset joe's 'realname'.
        results = self.server.set('joe', 'random', userid, 'realname=Joe Doe')
        results = self.server.display('joe', 'random', userid, 'realname')
        self.assertEqual(results['realname'], 'Joe Doe')
        # Create test
        results = self.server.create('joe', 'random', 'issue', 'title=foo')
        issueid = 'issue' + results
        results = self.server.display('joe', 'random', issueid, 'title')
        self.assertEqual(results['title'], 'foo')

class AuthenticationTestCase(TestCaseBase):

    def test(self):

        # Unknown user (caught in XMLRPC frontend).
        self.assertRaises(Unauthorised, self.server.list,
                          'nobody', 'nobody', 'user', 'id')
        # Wrong permissions (caught by roundup security module).
        results = self.server.list('joe', 'random', 'user', 'id')
        userid = 'user' + results[0] # admin
        # FIXME: why doesn't the following raise an exception ?
        # self.assertRaises(Unauthorised, self.server.set,
        #                  'joe', 'random', userid, 'realname=someone')


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(AccessTestCase))
    suite.addTest(unittest.makeSuite(AuthenticationTestCase))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)
