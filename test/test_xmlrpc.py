#
# Copyright (C) 2007 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

import unittest, os, shutil, errno, sys, difflib, cgi, re

from roundup.cgi.exceptions import *
from roundup import init, instance, password, hyperdb, date
from roundup.xmlrpc import RoundupServer
from roundup.backends import list_backends

import db_test_base

NEEDS_INSTANCE = 1

class TestCase(unittest.TestCase):

    backend = None

    def setUp(self):
        self.dirname = '_test_xmlrpc'
        # set up and open a tracker
        self.instance = db_test_base.setupTracker(self.dirname, self.backend)

        # open the database
        self.db = self.instance.open('admin')
        self.joeid = 'user' + self.db.user.create(username='joe',
            password=password.Password('random'), address='random@home.org',
            realname='Joe Random', roles='User')

        self.db.commit()
        self.db.close()

        self.server = RoundupServer(self.dirname)

    def tearDown(self):
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def testAccess(self):
        # Retrieve all three users.
        results = self.server.list('joe', 'random', 'user', 'id')
        self.assertEqual(len(results), 3)

        # Obtain data for 'joe'.
        results = self.server.display('joe', 'random', self.joeid)
        self.assertEqual(results['username'], 'joe')
        self.assertEqual(results['realname'], 'Joe Random')

    def testChange(self):
        # Reset joe's 'realname'.
        results = self.server.set('joe', 'random', self.joeid,
            'realname=Joe Doe')
        results = self.server.display('joe', 'random', self.joeid,
            'realname')
        self.assertEqual(results['realname'], 'Joe Doe')

        # check we can't change admin's details
        self.assertRaises(Unauthorised, self.server.set, 'joe', 'random',
            'user1', 'realname=Joe Doe')

    def testCreate(self):
        results = self.server.create('joe', 'random', 'issue', 'title=foo')
        issueid = 'issue' + results
        results = self.server.display('joe', 'random', issueid, 'title')
        self.assertEqual(results['title'], 'foo')

    def testFileCreate(self):
        results = self.server.create('joe', 'random', 'file', 'content=hello\r\nthere')
        fileid = 'file' + results
        results = self.server.display('joe', 'random', fileid, 'content')
        self.assertEqual(results['content'], 'hello\r\nthere')

    def testAuthUnknown(self):
        # Unknown user (caught in XMLRPC frontend).
        self.assertRaises(Unauthorised, self.server.list,
            'nobody', 'nobody', 'user', 'id')

    def testAuthDeniedEdit(self):
        # Wrong permissions (caught by roundup security module).
        self.assertRaises(Unauthorised, self.server.set,
            'joe', 'random', 'user1', 'realname=someone')

    def testAuthDeniedCreate(self):
        self.assertRaises(Unauthorised, self.server.create,
            'joe', 'random', 'user', {'username': 'blah'})

    def testAuthAllowedEdit(self):
        try:
            self.server.set('admin', 'sekrit', 'user2', 'realname=someone')
        except Unauthorised, err:
            self.fail('raised %s'%err)

    def testAuthAllowedCreate(self):
        try:
            self.server.create('admin', 'sekrit', 'user', 'username=blah')
        except Unauthorised, err:
            self.fail('raised %s'%err)

def test_suite():
    suite = unittest.TestSuite()
    for l in list_backends():
        dct = dict(backend = l)
        subcls = type(TestCase)('TestCase_%s'%l, (TestCase,), dct)
        suite.addTest(unittest.makeSuite(subcls))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)
