#
# Copyright (c) 2003 Richard Jones, rjones@ekit-inc.com
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# $Id: test_cgi.py,v 1.2 2003-01-14 22:21:35 richard Exp $

import unittest, os, shutil, errno, sys, difflib, cgi

from roundup.cgi import client
from roundup import init, instance, password

def makeForm(args):
    form = cgi.FieldStorage()
    for k,v in args.items():
        if type(v) is type([]):
            [form.list.append(cgi.MiniFieldStorage(k, x)) for x in v]
        else:
            form.list.append(cgi.MiniFieldStorage(k, v))
    return form

class FormTestCase(unittest.TestCase):
    def setUp(self):
        self.dirname = '_test_cgi_form'
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise
        # create the instance
        init.install(self.dirname, 'classic', 'anydbm')
        init.initialise(self.dirname, 'sekrit')
        # check we can load the package
        self.instance = instance.open(self.dirname)
        # and open the database
        self.db = self.instance.open('admin')
        self.db.user.create(username='Chef', address='chef@bork.bork.bork',
            realname='Bork, Chef', roles='User')
        self.db.user.create(username='mary', address='mary@test',
            roles='User', realname='Contrary, Mary')

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    #
    # Empty form
    #
    def testNothing(self):
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({})), {})

    def testNothingWithRequired(self):
        form = makeForm({':required': 'title'})
        self.assertRaises(ValueError, client.parsePropsFromForm, self.db,
            self.db.issue, form)

    #
    # String
    #
    def testEmptyString(self):
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'title': ''})), {})
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'title': ' '})), {})

    def testSetString(self):
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'title': 'foo'})), {'title': 'foo'})
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'title': 'a\r\nb\r\n'})), {'title': 'a\nb'})

    def testEmptyStringSet(self):
        nodeid = self.db.issue.create(title='foo')
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'title': ''}), nodeid), {'title': ''})
        nodeid = self.db.issue.create(title='foo')
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'title': ' '}), nodeid), {'title': ''})

    #
    # Multilink
    #
    def testEmptyMultilink(self):
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'nosy': ''})), {})
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'nosy': ' '})), {})

    def testSetMultilink(self):
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'nosy': '1'})), {'nosy': ['1']})
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'nosy': ['1','2']})), {'nosy': ['1','2']})
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'nosy': '1,2'})), {'nosy': ['1','2']})

    def testEmptyMultilinkSet(self):
        nodeid = self.db.issue.create(nosy=['1','2'])
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'nosy': ''}), nodeid), {'nosy': []})
        nodeid = self.db.issue.create(nosy=['1','2'])
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.issue,
            makeForm({'nosy': ' '}), nodeid), {'nosy': []})

    #
    # Password
    #
    def testEmptyPassword(self):
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.user,
            makeForm({'password': ''})), {})
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.user,
            makeForm({'password': ''})), {})

    def testSetPassword(self):
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.user,
            makeForm({'password': 'foo', 'password:confirm': 'foo'})),
            {'password': 'foo'})

    def testSetPasswordConfirmBad(self):
        self.assertRaises(ValueError, client.parsePropsFromForm, self.db,
            self.db.user, makeForm({'password': 'foo'}))
        self.assertRaises(ValueError, client.parsePropsFromForm, self.db,
            self.db.user, makeForm({'password': 'foo',
            'password:confirm': 'bar'}))

    def testEmptyPasswordNOTSet(self):
        nodeid = self.db.user.create(username='1', password=password.Password('foo'))
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.user,
            makeForm({'password': ''}), nodeid), {})
        nodeid = self.db.user.create(username='2', password=password.Password('foo'))
        self.assertEqual(client.parsePropsFromForm(self.db, self.db.user,
            makeForm({'password': '', 'password:confirm': ''}), nodeid), {})


def suite():
    l = [unittest.makeSuite(FormTestCase),
    ]
    return unittest.TestSuite(l)


# vim: set filetype=python ts=4 sw=4 et si
