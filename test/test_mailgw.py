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
# $Id: test_mailgw.py,v 1.37 2002-12-18 00:42:03 richard Exp $

import unittest, cStringIO, tempfile, os, shutil, errno, imp, sys, difflib

# Note: Should parse emails according to RFC2822 instead of performing a
# literal string comparision.  Parsing the messages allows the tests to work for
# any legal serialization of an email.
#try :
#    import email
#except ImportError :
#    import rfc822 as email

from roundup.mailgw import MailGW, Unauthorized
from roundup import init, instance

# TODO: make this output only enough equal lines for context, not all of
# them
class DiffHelper:
    def compareStrings(self, s2, s1):
        '''Note the reversal of s2 and s1 - difflib.SequenceMatcher wants
           the first to be the "original" but in the calls in this file,
           the second arg is the original. Ho hum.
        '''
        # we have to special-case the Date: header here 'cos we can't test
        # for it properly
        l1=s1.strip().split('\n')
        l2=[x for x in s2.strip().split('\n') if not x.startswith('Date: ')]
        if l1 == l2:
            return

        s = difflib.SequenceMatcher(None, l1, l2)
        res = ['Generated message not correct (diff follows):']
        for value, s1s, s1e, s2s, s2e in s.get_opcodes():
            if value == 'equal':
                for i in range(s1s, s1e):
                    res.append('  %s'%l1[i])
            elif value == 'delete':
                for i in range(s1s, s1e):
                    res.append('- %s'%l1[i])
            elif value == 'insert':
                for i in range(s2s, s2e):
                    res.append('+ %s'%l2[i])
            elif value == 'replace':
                for i, j in zip(range(s1s, s1e), range(s2s, s2e)):
                    res.append('- %s'%l1[i])
                    res.append('+ %s'%l2[j])

        raise AssertionError, '\n'.join(res)

class MailgwTestCase(unittest.TestCase, DiffHelper):
    count = 0
    schema = 'classic'
    def setUp(self):
        MailgwTestCase.count = MailgwTestCase.count + 1
        self.dirname = '_test_mailgw_%s'%self.count
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
        self.db.user.create(username='richard', address='richard@test',
            roles='User')
        self.db.user.create(username='mary', address='mary@test',
            roles='User', realname='Contrary, Mary')
        self.db.user.create(username='john', address='john@test',
            alternate_addresses='jondoe@test\njohn.doe@test', roles='User',
            realname='John Doe')

    def tearDown(self):
        if os.path.exists(os.environ['SENDMAILDEBUG']):
            os.remove(os.environ['SENDMAILDEBUG'])
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def doNewIssue(self):
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        nodeid = handler.main(message)
        if os.path.exists(os.environ['SENDMAILDEBUG']):
            error = open(os.environ['SENDMAILDEBUG']).read()
            self.assertEqual('no error', error)
        l = self.db.issue.get(nodeid, 'nosy')
        l.sort()
        self.assertEqual(l, ['3', '4'])
        return nodeid

    def testNewIssue(self):
        self.doNewIssue()

    def testNewIssueNosy(self):
        self.instance.config.ADD_AUTHOR_TO_NOSY = 'yes'
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        nodeid = handler.main(message)
        if os.path.exists(os.environ['SENDMAILDEBUG']):
            error = open(os.environ['SENDMAILDEBUG']).read()
            self.assertEqual('no error', error)
        l = self.db.issue.get(nodeid, 'nosy')
        l.sort()
        self.assertEqual(l, ['3', '4'])

    def testAlternateAddress(self):
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: John Doe <john.doe@test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
''')
        userlist = self.db.user.list()
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)
        if os.path.exists(os.environ['SENDMAILDEBUG']):
            error = open(os.environ['SENDMAILDEBUG']).read()
            self.assertEqual('no error', error)
        self.assertEqual(userlist, self.db.user.list(),
            "user created when it shouldn't have been")

    def testNewIssueNoClass(self):
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test
Message-Id: <dummy_test_message_id>
Subject: Testing...

This is a test submission of a new issue.
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)
        if os.path.exists(os.environ['SENDMAILDEBUG']):
            error = open(os.environ['SENDMAILDEBUG']).read()
            self.assertEqual('no error', error)

    def testNewIssueAuthMsg(self):
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing... [nosy=mary; assignedto=richard]

This is a test submission of a new issue.
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        # TODO: fix the damn config - this is apalling
        self.db.config.MESSAGES_TO_AUTHOR = 'yes'
        handler.main(message)

        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, mary@test, richard@test
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork, mary@test, richard@test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


New submission from Bork, Chef <chef@bork.bork.bork>:

This is a test submission of a new issue.


----------
assignedto: richard
messages: 1
nosy: Chef, mary, richard
status: unread
title: Testing...
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________
''')

    # BUG
    # def testMultipart(self):
    #         '''With more than one part'''
    #        see MultipartEnc tests: but if there is more than one part
    #        we return a multipart/mixed and the boundary contains
    #        the ip address of the test machine. 

    # BUG should test some binary attamchent too.

    def testSimpleFollowup(self):
        self.doNewIssue()
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: mary <mary@test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a second followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)
        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test> added the comment:

This is a second followup


----------
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________
''')

    def testFollowup(self):
        self.doNewIssue()

        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing... [assignedto=mary; nosy=+john]

This is a followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)
        l = self.db.issue.get('1', 'nosy')
        l.sort()
        self.assertEqual(l, ['3', '4', '5', '6'])

        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test, mary@test
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork, john@test, mary@test
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


richard <richard@test> added the comment:

This is a followup


----------
assignedto:  -> mary
nosy: +john, mary
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________
''')

    def testFollowupTitleMatch(self):
        self.doNewIssue()
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: Re: Testing... [assignedto=mary; nosy=+john]

This is a followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)

        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test, mary@test
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork, john@test, mary@test
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


richard <richard@test> added the comment:

This is a followup


----------
assignedto:  -> mary
nosy: +john, mary
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________
''')

    def testFollowupNosyAuthor(self):
        self.doNewIssue()
        self.db.config.ADD_AUTHOR_TO_NOSY = 'yes'
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: john@test
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)

        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


John Doe <john@test> added the comment:

This is a followup


----------
nosy: +john
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________

''')

    def testFollowupNosyRecipients(self):
        self.doNewIssue()
        self.db.config.ADD_RECIPIENTS_TO_NOSY = 'yes'
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard@test
To: issue_tracker@your.tracker.email.domain.example
Cc: john@test
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)

        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


richard <richard@test> added the comment:

This is a followup


----------
nosy: +john
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________

''')

    def testFollowupNosyAuthorAndCopy(self):
        self.doNewIssue()
        self.db.config.ADD_AUTHOR_TO_NOSY = 'yes'
        self.db.config.MESSAGES_TO_AUTHOR = 'yes'
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: john@test
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)

        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test, richard@test
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork, john@test, richard@test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


John Doe <john@test> added the comment:

This is a followup


----------
nosy: +john
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________

''')

    def testFollowupNoNosyAuthor(self):
        self.doNewIssue()
        self.instance.config.ADD_AUTHOR_TO_NOSY = 'no'
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: john@test
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)

        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


John Doe <john@test> added the comment:

This is a followup


----------
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________

''')

    def testFollowupNoNosyRecipients(self):
        self.doNewIssue()
        self.instance.config.ADD_RECIPIENTS_TO_NOSY = 'no'
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard@test
To: issue_tracker@your.tracker.email.domain.example
Cc: john@test
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)

        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


richard <richard@test> added the comment:

This is a followup


----------
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________

''')

    def testNosyRemove(self):
        self.doNewIssue()

        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing... [nosy=-richard]

''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)
        l = self.db.issue.get('1', 'nosy')
        l.sort()
        self.assertEqual(l, ['3'])

        # NO NOSY MESSAGE SHOULD BE SENT!
        self.assert_(not os.path.exists(os.environ['SENDMAILDEBUG']))

    def testNewUserAuthor(self):
        # first without the permission
        # heh... just ignore the API for a second ;)
        self.db.security.role['Anonymous'].permissions=[]
        anonid = self.db.user.lookup('anonymous')
        self.db.user.set(anonid, roles='Anonymous')

        self.db.security.hasPermission('Email Registration', anonid)
        l = self.db.user.list()
        l.sort()
        s = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: fubar <fubar@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
'''
        message = cStringIO.StringIO(s)
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        self.assertRaises(Unauthorized, handler.main, message)
        m = self.db.user.list()
        m.sort()
        self.assertEqual(l, m)

        # now with the permission
        p = self.db.security.getPermission('Email Registration')
        self.db.security.role['Anonymous'].permissions=[p]
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        message = cStringIO.StringIO(s)
        handler.main(message)
        m = self.db.user.list()
        m.sort()
        self.assertNotEqual(l, m)

    def testEnc01(self):
        self.doNewIssue()
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: mary <mary@test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: text/plain;
        charset="iso-8859-1"
Content-Transfer-Encoding: quoted-printable

A message with encoding (encoded oe =F6)

''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)
        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test> added the comment:

A message with encoding (encoded oe =F6)

----------
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________
''')


    def testMultipartEnc01(self):
        self.doNewIssue()
        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: mary <mary@test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: multipart/mixed;
        boundary="----_=_NextPart_000_01"

This message is in MIME format. Since your mail reader does not understand
this format, some or all of this message may not be legible.

------_=_NextPart_000_01
Content-Type: text/plain;
        charset="iso-8859-1"
Content-Transfer-Encoding: quoted-printable

A message with first part encoded (encoded oe =F6)

''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)
        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test> added the comment:

A message with first part encoded (encoded oe =F6)

----------
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________
''')

    def testFollowupStupidQuoting(self):
        self.doNewIssue()

        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: Re: "[issue1] Testing... "

This is a followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)

        self.compareStrings(open(os.environ['SENDMAILDEBUG']).read(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork
Content-Type: text/plain
Subject: [issue1] Testing...
To: chef@bork.bork.bork
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: quoted-printable


richard <richard@test> added the comment:

This is a followup


----------
status: unread -> chatting
_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1
_______________________________________________________________________
''')

    def testEmailQuoting(self):
        self.instance.config.EMAIL_KEEP_QUOTED_TEXT = 'no'
        self.innerTestQuoting('''This is a followup
''')

    def testEmailQuotingRemove(self):
        self.instance.config.EMAIL_KEEP_QUOTED_TEXT = 'yes'
        self.innerTestQuoting('''Blah blah wrote:
> Blah bklaskdfj sdf asdf jlaskdf skj sdkfjl asdf
>  skdjlkjsdfalsdkfjasdlfkj dlfksdfalksd fj
>

This is a followup
''')

    def innerTestQuoting(self, expect):
        nodeid = self.doNewIssue()

        messages = self.db.issue.get(nodeid, 'messages')

        message = cStringIO.StringIO('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: Re: [issue1] Testing...

Blah blah wrote:
> Blah bklaskdfj sdf asdf jlaskdf skj sdkfjl asdf
>  skdjlkjsdfalsdkfjasdlfkj dlfksdfalksd fj
>

This is a followup
''')
        handler = self.instance.MailGW(self.instance, self.db)
        handler.trapExceptions = 0
        handler.main(message)

        # figure the new message id
        newmessages = self.db.issue.get(nodeid, 'messages')
        for msg in messages:
            newmessages.remove(msg)
        messageid = newmessages[0]

        self.compareStrings(self.db.msg.get(messageid, 'content'), expect)

def suite():
    l = [unittest.makeSuite(MailgwTestCase),
    ]
    return unittest.TestSuite(l)


# vim: set filetype=python ts=4 sw=4 et si
