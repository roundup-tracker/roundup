#
# Copyright (c) 2001 Richard Jones, richard@bofh.asn.au.
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# $Id: test_mailgw.py,v 1.1 2002-01-02 02:31:38 richard Exp $

import unittest, cStringIO, tempfile, os, shutil, errno, imp, sys

from roundup.mailgw import MailGW
from roundup import init, instance

class MailgwTestCase(unittest.TestCase):
    count = 0
    schema = 'classic'
    def setUp(self):
        MailgwTestCase.count = MailgwTestCase.count + 1
        self.dirname = '_test_%s'%self.count
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise
        # create the instance
        init.init(self.dirname, self.schema, 'anydbm', 'sekrit')
        # check we can load the package
        self.instance = instance.open(self.dirname)
        # and open the database
        self.db = self.instance.open('sekrit')
        self.db.user.create(username='Chef', address='chef@bork.bork.bork')
        self.db.user.create(username='richard', address='richard@test')

    def tearDown(self):
        if os.path.exists(os.environ['SENDMAILDEBUG']):
            os.remove(os.environ['SENDMAILDEBUG'])
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def testNewIssue(self):
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork
To: issue_tracker@fill.me.in.
Cc: richard@test
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.main(message)
        if os.path.exists(os.environ['SENDMAILDEBUG']):
            error = open(os.environ['SENDMAILDEBUG']).read()
            self.assertEqual('no error', error)

    def testNewIssueAuthMsg(self):
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork
To: issue_tracker@fill.me.in.
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
''')
        handler = self.instance.MailGW(self.instance, self.db)
        # TODO: fix the damn config - this is apalling
        self.instance.IssueClass.MESSAGES_TO_AUTHOR = 'yes'
        handler.main(message)

        self.assertEqual(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@fill.me.in.
TO: chef@bork.bork.bork
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork
From: Chef <issue_tracker@fill.me.in.>
Reply-To: Roundup issue tracker <issue_tracker@fill.me.in.>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>


New submission from Chef <chef@bork.bork.bork>:

This is a test submission of a new issue.

___________________________________________________
"Roundup issue tracker" <issue_tracker@fill.me.in.>
http://some.useful.url/issue1
___________________________________________________
''', 'Generated message not correct')

    def testFollowup(self):
        self.testNewIssue()
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test>
To: issue_tracker@fill.me.in.
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        # TODO: fix the damn config - this is apalling
        handler.main(message)

        self.assertEqual(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@fill.me.in.
TO: chef@bork.bork.bork
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork
From: richard <issue_tracker@fill.me.in.>
Reply-To: Roundup issue tracker <issue_tracker@fill.me.in.>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>


richard <richard@test> added the comment:

This is a followup

___________________________________________________
"Roundup issue tracker" <issue_tracker@fill.me.in.>
http://some.useful.url/issue1
___________________________________________________
''', 'Generated message not correct')

class ExtMailgwTestCase(MailgwTestCase):
    schema = 'extended'

def suite():
    l = [unittest.makeSuite(MailgwTestCase, 'test'),
        unittest.makeSuite(ExtMailgwTestCase, 'test')]
    return unittest.TestSuite(l)


#
# $Log: not supported by cvs2svn $
#
#
#
# vim: set filetype=python ts=4 sw=4 et si
