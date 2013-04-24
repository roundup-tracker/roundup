#
# Copyright (C) 2007 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

import unittest, os, shutil, errno, sys, difflib, cgi, re

from roundup.cgi.exceptions import *
from roundup import init, instance, password, hyperdb, date
from roundup.xmlrpc import RoundupInstance
from roundup.backends import list_backends
from roundup.hyperdb import String

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

        # Get user id (user4 maybe). Used later to get data from db.
        self.joeid = 'user' + self.db.user.create(username='joe',
            password=password.Password('random'), address='random@home.org',
            realname='Joe Random', roles='User')

        self.db.commit()
        self.db.close()
        self.db = self.instance.open('joe')

        self.db.tx_Source = 'web'

        self.db.issue.addprop(tx_Source=hyperdb.String())
        self.db.msg.addprop(tx_Source=hyperdb.String())

        self.db.post_init()

        vars = dict(globals())
        vars['db'] = self.db
        vars = {}
        execfile("test/tx_Source_detector.py", vars)
        vars['init'](self.db)

        self.server = RoundupInstance(self.db, self.instance.actions, None)

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def testAccess(self):
        # Retrieve all three users.
        results = self.server.list('user', 'id')
        self.assertEqual(len(results), 3)

        # Obtain data for 'joe'.
        results = self.server.display(self.joeid)
        self.assertEqual(results['username'], 'joe')
        self.assertEqual(results['realname'], 'Joe Random')

    def testChange(self):
        # Reset joe's 'realname'.
        results = self.server.set(self.joeid, 'realname=Joe Doe')
        results = self.server.display(self.joeid, 'realname')
        self.assertEqual(results['realname'], 'Joe Doe')

        # check we can't change admin's details
        self.assertRaises(Unauthorised, self.server.set, 'user1', 'realname=Joe Doe')

    def testCreate(self):
        results = self.server.create('issue', 'title=foo')
        issueid = 'issue' + results
        results = self.server.display(issueid, 'title')
        self.assertEqual(results['title'], 'foo')
        self.assertEqual(self.db.issue.get('1', "tx_Source"), 'web')

    def testFileCreate(self):
        results = self.server.create('file', 'content=hello\r\nthere')
        fileid = 'file' + results
        results = self.server.display(fileid, 'content')
        self.assertEqual(results['content'], 'hello\r\nthere')

    def testAction(self):
        # As this action requires special previledges, we temporarily switch
        # to 'admin'
        self.db.setCurrentUser('admin')
        users_before = self.server.list('user')
        try:
            tmp = 'user' + self.db.user.create(username='tmp')
            self.server.action('retire', tmp)
        finally:
            self.db.setCurrentUser('joe')
        users_after = self.server.list('user')
        self.assertEqual(users_before, users_after)

    def testAuthDeniedEdit(self):
        # Wrong permissions (caught by roundup security module).
        self.assertRaises(Unauthorised, self.server.set,
                          'user1', 'realname=someone')

    def testAuthDeniedCreate(self):
        self.assertRaises(Unauthorised, self.server.create,
                          'user', {'username': 'blah'})

    def testAuthAllowedEdit(self):
        self.db.setCurrentUser('admin')
        try:
            try:
                self.server.set('user2', 'realname=someone')
            except Unauthorised, err:
                self.fail('raised %s'%err)
        finally:
            self.db.setCurrentUser('joe')

    def testAuthAllowedCreate(self):
        self.db.setCurrentUser('admin')
        try:
            try:
                self.server.create('user', 'username=blah')
            except Unauthorised, err:
                self.fail('raised %s'%err)
        finally:
            self.db.setCurrentUser('joe')

    def testAuthFilter(self):
        # this checks if we properly check for search permissions
        self.db.security.permissions = {}
        self.db.security.addRole(name='User')
        self.db.security.addRole(name='Project')
        self.db.security.addPermissionToRole('User', 'Web Access')
        self.db.security.addPermissionToRole('Project', 'Web Access')
        # Allow viewing keyword
        p = self.db.security.addPermission(name='View', klass='keyword')
        self.db.security.addPermissionToRole('User', p)
        # Allow viewing interesting things (but not keyword) on issue
        # But users might only view issues where they are on nosy
        # (so in the real world the check method would be better)
        p = self.db.security.addPermission(name='View', klass='issue',
            properties=("title", "status"), check=lambda x,y,z: True)
        self.db.security.addPermissionToRole('User', p)
        # Allow role "Project" access to whole issue
        p = self.db.security.addPermission(name='View', klass='issue')
        self.db.security.addPermissionToRole('Project', p)
        # Allow all access to status:
        p = self.db.security.addPermission(name='View', klass='status')
        self.db.security.addPermissionToRole('User', p)
        self.db.security.addPermissionToRole('Project', p)

        keyword = self.db.keyword
        status = self.db.status
        issue = self.db.issue

        d1 = keyword.create(name='d1')
        d2 = keyword.create(name='d2')
        open = status.create(name='open')
        closed = status.create(name='closed')
        issue.create(title='i1', status=open, keyword=[d2])
        issue.create(title='i2', status=open, keyword=[d1])
        issue.create(title='i2', status=closed, keyword=[d1])

        chef = self.db.user.create(username = 'chef', roles='User, Project')
        joe  = self.db.user.lookup('joe')

        # Conditionally allow view of whole issue (check is False here,
        # this might check for keyword owner in the real world)
        p = self.db.security.addPermission(name='View', klass='issue',
            check=lambda x,y,z: False)
        self.db.security.addPermissionToRole('User', p)
        # Allow user to search for issue.status
        p = self.db.security.addPermission(name='Search', klass='issue',
            properties=("status",))
        self.db.security.addPermissionToRole('User', p)

        keyw = {'keyword':self.db.keyword.lookup('d1')}
        stat = {'status':self.db.status.lookup('open')}
        keygroup = keysort = [('+', 'keyword')]
        self.db.commit()

        # Filter on keyword ignored for role 'User':
        r = self.server.filter('issue', None, keyw)
        self.assertEqual(r, ['1', '2', '3'])
        # Filter on status works for all:
        r = self.server.filter('issue', None, stat)
        self.assertEqual(r, ['1', '2'])
        # Sorting and grouping for class User fails:
        r = self.server.filter('issue', None, {}, sort=keysort)
        self.assertEqual(r, ['1', '2', '3'])
        r = self.server.filter('issue', None, {}, group=keygroup)
        self.assertEqual(r, ['1', '2', '3'])

        self.db.close()
        self.db = self.instance.open('chef')
        self.db.tx_Source = 'web'

        self.db.issue.addprop(tx_Source=hyperdb.String())
        self.db.msg.addprop(tx_Source=hyperdb.String())
        self.db.post_init()

        self.server = RoundupInstance(self.db, self.instance.actions, None)

        # Filter on keyword works for role 'Project':
        r = self.server.filter('issue', None, keyw)
        self.assertEqual(r, ['2', '3'])
        # Filter on status works for all:
        r = self.server.filter('issue', None, stat)
        self.assertEqual(r, ['1', '2'])
        # Sorting and grouping for class Project works:
        r = self.server.filter('issue', None, {}, sort=keysort)
        self.assertEqual(r, ['2', '3', '1'])
        r = self.server.filter('issue', None, {}, group=keygroup)
        self.assertEqual(r, ['2', '3', '1'])

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
