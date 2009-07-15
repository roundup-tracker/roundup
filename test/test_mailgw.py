# -*- encoding: utf-8 -*-
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
# $Id: test_mailgw.py,v 1.96 2008-08-19 01:40:59 richard Exp $

# TODO: test bcc

import unittest, tempfile, os, shutil, errno, imp, sys, difflib, rfc822, time

from cStringIO import StringIO

if not os.environ.has_key('SENDMAILDEBUG'):
    os.environ['SENDMAILDEBUG'] = 'mail-test.log'
SENDMAILDEBUG = os.environ['SENDMAILDEBUG']

from roundup.mailgw import MailGW, Unauthorized, uidFromAddress, \
    parseContent, IgnoreLoop, IgnoreBulk, MailUsageError, MailUsageHelp
from roundup import init, instance, password, rfc2822, __version__
from roundup.anypy.sets_ import set

import db_test_base

class Message(rfc822.Message):
    """String-based Message class with equivalence test."""
    def __init__(self, s):
        rfc822.Message.__init__(self, StringIO(s.strip()))

    def __eq__(self, other):
        return (self.dict == other.dict and
                self.fp.read() == other.fp.read())

class DiffHelper:
    def compareMessages(self, new, old):
        """Compare messages for semantic equivalence."""
        new, old = Message(new), Message(old)

        # all Roundup-generated messages have "Precedence: bulk"
        old['Precedence'] = 'bulk'

        # don't try to compare the date
        del new['date'], old['date']

        if not new == old:
            res = []

            replace = {}
            for key in new.keys():
                if key.startswith('from '):
                    # skip the unix from line
                    continue
                if key.lower() == 'x-roundup-version':
                    # version changes constantly, so handle it specially
                    if new[key] != __version__:
                        res.append('  %s: %r != %r' % (key, __version__,
                            new[key]))
                elif key.lower() == 'content-type' and 'boundary=' in new[key]:
                    # handle mime messages
                    newmime = new[key].split('=',1)[-1].strip('"')
                    oldmime = old.get(key, '').split('=',1)[-1].strip('"')
                    replace ['--' + newmime] = '--' + oldmime
                    replace ['--' + newmime + '--'] = '--' + oldmime + '--'
                elif new.get(key, '') != old.get(key, ''):
                    res.append('  %s: %r != %r' % (key, old.get(key, ''),
                        new.get(key, '')))

            body_diff = self.compareStrings(new.fp.read(), old.fp.read(),
                replace=replace)
            if body_diff:
                res.append('')
                res.extend(body_diff)

            if res:
                res.insert(0, 'Generated message not correct (diff follows):')
                raise AssertionError, '\n'.join(res)

    def compareStrings(self, s2, s1, replace={}):
        '''Note the reversal of s2 and s1 - difflib.SequenceMatcher wants
           the first to be the "original" but in the calls in this file,
           the second arg is the original. Ho hum.
           Do replacements over the replace dict -- used for mime boundary
        '''
        l1 = s1.strip().split('\n')
        l2 = [replace.get(i,i) for i in s2.strip().split('\n')]
        if l1 == l2:
            return
        s = difflib.SequenceMatcher(None, l1, l2)
        res = []
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

        return res

class MailgwTestCase(unittest.TestCase, DiffHelper):
    count = 0
    schema = 'classic'
    def setUp(self):
        MailgwTestCase.count = MailgwTestCase.count + 1
        self.dirname = '_test_mailgw_%s'%self.count
        # set up and open a tracker
        self.instance = db_test_base.setupTracker(self.dirname)

        # and open the database
        self.db = self.instance.open('admin')
        self.chef_id = self.db.user.create(username='Chef',
            address='chef@bork.bork.bork', realname='Bork, Chef', roles='User')
        self.richard_id = self.db.user.create(username='richard',
            address='richard@test.test', roles='User')
        self.mary_id = self.db.user.create(username='mary',
            address='mary@test.test', roles='User', realname='Contrary, Mary')
        self.john_id = self.db.user.create(username='john',
            address='john@test.test', roles='User', realname='John Doe',
            alternate_addresses='jondoe@test.test\njohn.doe@test.test')

    def tearDown(self):
        if os.path.exists(SENDMAILDEBUG):
            os.remove(SENDMAILDEBUG)
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def _handle_mail(self, message):
        # handler will open a new db handle. On single-threaded
        # databases we'll have to close our current connection
        self.db.commit()
        self.db.close()
        handler = self.instance.MailGW(self.instance)
        handler.trapExceptions = 0
        ret = handler.main(StringIO(message))
        # handler had its own database, open new connection
        self.db = self.instance.open('admin')
        return ret

    def _get_mail(self):
        f = open(SENDMAILDEBUG)
        try:
            return f.read()
        finally:
            f.close()

    def testEmptyMessage(self):
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'), 'Testing...')

    def doNewIssue(self):
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
''')
        assert not os.path.exists(SENDMAILDEBUG)
        l = self.db.issue.get(nodeid, 'nosy')
        l.sort()
        self.assertEqual(l, [self.chef_id, self.richard_id])
        return nodeid

    def testNewIssue(self):
        self.doNewIssue()

    def testNewIssueNosy(self):
        self.instance.config.ADD_AUTHOR_TO_NOSY = 'yes'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
''')
        assert not os.path.exists(SENDMAILDEBUG)
        l = self.db.issue.get(nodeid, 'nosy')
        l.sort()
        self.assertEqual(l, [self.chef_id, self.richard_id])

    def testAlternateAddress(self):
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: John Doe <john.doe@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
''')
        userlist = self.db.user.list()
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(userlist, self.db.user.list(),
            "user created when it shouldn't have been")

    def testNewIssueNoClass(self):
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Message-Id: <dummy_test_message_id>
Subject: Testing...

This is a test submission of a new issue.
''')
        assert not os.path.exists(SENDMAILDEBUG)

    def testNewIssueAuthMsg(self):
        # TODO: fix the damn config - this is apalling
        self.db.config.MESSAGES_TO_AUTHOR = 'yes'
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing... [nosy=mary; assignedto=richard]

This is a test submission of a new issue.
''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
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
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testNewIssueNoAuthorInfo(self):
        self.db.config.MAIL_ADD_AUTHORINFO = 'no'
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing... [nosy=mary; assignedto=richard]

This is a test submission of a new issue.
''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
Content-Transfer-Encoding: quoted-printable

This is a test submission of a new issue.

----------
assignedto: richard
messages: 1
nosy: Chef, mary, richard
status: unread
title: Testing...

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testNewIssueNoAuthorEmail(self):
        self.db.config.MAIL_ADD_AUTHOREMAIL = 'no'
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing... [nosy=mary; assignedto=richard]

This is a test submission of a new issue.
''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
Content-Transfer-Encoding: quoted-printable

New submission from Bork, Chef:

This is a test submission of a new issue.

----------
assignedto: richard
messages: 1
nosy: Chef, mary, richard
status: unread
title: Testing...

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    multipart_msg = '''From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: multipart/mixed; boundary="bxyzzy"
Content-Disposition: inline


--bxyzzy
Content-Type: multipart/alternative; boundary="bCsyhTFzCvuiizWE"
Content-Disposition: inline

--bCsyhTFzCvuiizWE
Content-Type: text/plain; charset=us-ascii
Content-Disposition: inline

test attachment first text/plain

--bCsyhTFzCvuiizWE
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="first.dvi"
Content-Transfer-Encoding: base64

SnVzdCBhIHRlc3QgAQo=

--bCsyhTFzCvuiizWE
Content-Type: text/plain; charset=us-ascii
Content-Disposition: inline

test attachment second text/plain

--bCsyhTFzCvuiizWE
Content-Type: text/html
Content-Disposition: inline

<html>
to be ignored.
</html>

--bCsyhTFzCvuiizWE--

--bxyzzy
Content-Type: multipart/alternative; boundary="bCsyhTFzCvuiizWF"
Content-Disposition: inline

--bCsyhTFzCvuiizWF
Content-Type: text/plain; charset=us-ascii
Content-Disposition: inline

test attachment third text/plain

--bCsyhTFzCvuiizWF
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="second.dvi"
Content-Transfer-Encoding: base64

SnVzdCBhIHRlc3QK

--bCsyhTFzCvuiizWF--

--bxyzzy--
'''

    def testMultipartKeepAlternatives(self):
        self.doNewIssue()
        self._handle_mail(self.multipart_msg)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        assert(len(msg.files) == 5)
        names = {0 : 'first.dvi', 4 : 'second.dvi'}
        content = {3 : 'test attachment third text/plain\n',
                   4 : 'Just a test\n'}
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, names.get (n, 'unnamed'))
            if n in content :
                self.assertEqual(f.content, content [n])
        self.assertEqual(msg.content, 'test attachment second text/plain')

    def testMultipartDropAlternatives(self):
        self.doNewIssue()
        self.db.config.MAILGW_IGNORE_ALTERNATIVES = True
        self._handle_mail(self.multipart_msg)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        assert(len(msg.files) == 2)
        names = {1 : 'second.dvi'}
        content = {0 : 'test attachment third text/plain\n',
                   1 : 'Just a test\n'}
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, names.get (n, 'unnamed'))
            if n in content :
                self.assertEqual(f.content, content [n])
        self.assertEqual(msg.content, 'test attachment second text/plain')

    def testSimpleFollowup(self):
        self.doNewIssue()
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a second followup
''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test.test> added the comment:

This is a second followup

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testFollowup(self):
        self.doNewIssue()

        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing... [assignedto=mary; nosy=+john]

This is a followup
''')
        l = self.db.issue.get('1', 'nosy')
        l.sort()
        self.assertEqual(l, [self.chef_id, self.richard_id, self.mary_id,
            self.john_id])

        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test.test, mary@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, john@test.test, mary@test.test
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


richard <richard@test.test> added the comment:

This is a followup

----------
assignedto:  -> mary
nosy: +john, mary
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testPropertyChangeOnly(self):
        self.doNewIssue()
        oldvalues = self.db.getnode('issue', '1').copy()
        oldvalues['assignedto'] = None
        # reconstruct old behaviour: This would reuse the
        # database-handle from the doNewIssue above which has committed
        # as user "Chef". So we close and reopen the db as that user.
        self.db.close()
        self.db = self.instance.open('Chef')
        self.db.issue.set('1', assignedto=self.chef_id)
        self.db.commit()
        self.db.issue.nosymessage('1', None, oldvalues)

        new_mail = ""
        for line in self._get_mail().split("\n"):
            if "Message-Id: " in line:
                continue
            if "Date: " in line:
                continue
            new_mail += line+"\n"

        self.compareMessages(new_mail, """
FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
X-Roundup-Version: 1.3.3
MIME-Version: 1.0
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
Content-Transfer-Encoding: quoted-printable


Change by Bork, Chef <chef@bork.bork.bork>:


----------
assignedto:  -> Chef

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
""")


    #
    # FOLLOWUP TITLE MATCH
    #
    def testFollowupTitleMatch(self):
        self.doNewIssue()
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
Subject: Re: Testing... [assignedto=mary; nosy=+john]

This is a followup
''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test.test, mary@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, john@test.test, mary@test.test
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


richard <richard@test.test> added the comment:

This is a followup

----------
assignedto:  -> mary
nosy: +john, mary
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testFollowupTitleMatchMultiRe(self):
        nodeid1 = self.doNewIssue()
        nodeid2 = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
Subject: Re: Testing... [assignedto=mary; nosy=+john]

This is a followup
''')

        nodeid3 = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup2_dummy_id>
Subject: Ang: Re: Testing...

This is a followup
''')
        self.assertEqual(nodeid1, nodeid2)
        self.assertEqual(nodeid1, nodeid3)

    def testFollowupTitleMatchNever(self):
        nodeid = self.doNewIssue()
        self.db.config.MAILGW_SUBJECT_CONTENT_MATCH = 'never'
        self.assertNotEqual(self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
Subject: Re: Testing...

This is a followup
'''), nodeid)

    def testFollowupTitleMatchNeverInterval(self):
        nodeid = self.doNewIssue()
        # force failure of the interval
        time.sleep(2)
        self.db.config.MAILGW_SUBJECT_CONTENT_MATCH = 'creation 00:00:01'
        self.assertNotEqual(self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
Subject: Re: Testing...

This is a followup
'''), nodeid)


    def testFollowupTitleMatchInterval(self):
        nodeid = self.doNewIssue()
        self.db.config.MAILGW_SUBJECT_CONTENT_MATCH = 'creation +1d'
        self.assertEqual(self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
Subject: Re: Testing...

This is a followup
'''), nodeid)


    def testFollowupNosyAuthor(self):
        self.doNewIssue()
        self.db.config.ADD_AUTHOR_TO_NOSY = 'yes'
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: john@test.test
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')

        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


John Doe <john@test.test> added the comment:

This is a followup

----------
nosy: +john
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________

''')

    def testFollowupNosyRecipients(self):
        self.doNewIssue()
        self.db.config.ADD_RECIPIENTS_TO_NOSY = 'yes'
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard@test.test
To: issue_tracker@your.tracker.email.domain.example
Cc: john@test.test
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


richard <richard@test.test> added the comment:

This is a followup

----------
nosy: +john
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________

''')

    def testFollowupNosyAuthorAndCopy(self):
        self.doNewIssue()
        self.db.config.ADD_AUTHOR_TO_NOSY = 'yes'
        self.db.config.MESSAGES_TO_AUTHOR = 'yes'
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: john@test.test
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, john@test.test, richard@test.test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


John Doe <john@test.test> added the comment:

This is a followup

----------
nosy: +john
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________

''')

    def testFollowupNoNosyAuthor(self):
        self.doNewIssue()
        self.instance.config.ADD_AUTHOR_TO_NOSY = 'no'
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: john@test.test
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


John Doe <john@test.test> added the comment:

This is a followup

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________

''')

    def testFollowupNoNosyRecipients(self):
        self.doNewIssue()
        self.instance.config.ADD_RECIPIENTS_TO_NOSY = 'no'
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard@test.test
To: issue_tracker@your.tracker.email.domain.example
Cc: john@test.test
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


richard <richard@test.test> added the comment:

This is a followup

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________

''')

    def testFollowupEmptyMessage(self):
        self.doNewIssue()

        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing... [assignedto=mary; nosy=+john]

''')
        l = self.db.issue.get('1', 'nosy')
        l.sort()
        self.assertEqual(l, [self.chef_id, self.richard_id, self.mary_id,
            self.john_id])

        # should be no file created (ie. no message)
        assert not os.path.exists(SENDMAILDEBUG)

    def testFollowupEmptyMessageNoSubject(self):
        self.doNewIssue()

        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] [assignedto=mary; nosy=+john]

''')
        l = self.db.issue.get('1', 'nosy')
        l.sort()
        self.assertEqual(l, [self.chef_id, self.richard_id, self.mary_id,
            self.john_id])

        # should be no file created (ie. no message)
        assert not os.path.exists(SENDMAILDEBUG)

    def testNosyRemove(self):
        self.doNewIssue()

        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing... [nosy=-richard]

''')
        l = self.db.issue.get('1', 'nosy')
        l.sort()
        self.assertEqual(l, [self.chef_id])

        # NO NOSY MESSAGE SHOULD BE SENT!
        assert not os.path.exists(SENDMAILDEBUG)

    def testNewUserAuthor(self):

        l = self.db.user.list()
        l.sort()
        message = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: fubar <fubar@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
'''
        def hook (db, **kw):
            ''' set up callback for db open '''
            db.security.role['anonymous'].permissions=[]
            anonid = db.user.lookup('anonymous')
            db.user.set(anonid, roles='Anonymous')
        self.instance.schema_hook = hook
        try:
            self._handle_mail(message)
        except Unauthorized, value:
            body_diff = self.compareMessages(str(value), """
You are not a registered user.

Unknown address: fubar@bork.bork.bork
""")

            assert not body_diff, body_diff

        else:
            raise AssertionError, "Unathorized not raised when handling mail"


        def hook (db, **kw):
            ''' set up callback for db open '''
            # Add Web Access role to anonymous, and try again to make sure
            # we get a "please register at:" message this time.
            p = [
                db.security.getPermission('Create', 'user'),
                db.security.getPermission('Web Access', None),
            ]
            db.security.role['anonymous'].permissions=p
        self.instance.schema_hook = hook
        try:
            self._handle_mail(message)
        except Unauthorized, value:
            body_diff = self.compareMessages(str(value), """
You are not a registered user. Please register at:

http://tracker.example/cgi-bin/roundup.cgi/bugs/user?template=register

...before sending mail to the tracker.

Unknown address: fubar@bork.bork.bork
""")

            assert not body_diff, body_diff

        else:
            raise AssertionError, "Unathorized not raised when handling mail"

        # Make sure list of users is the same as before.
        m = self.db.user.list()
        m.sort()
        self.assertEqual(l, m)

        def hook (db, **kw):
            ''' set up callback for db open '''
            # now with the permission
            p = [
                db.security.getPermission('Create', 'user'),
                db.security.getPermission('Email Access', None),
            ]
            db.security.role['anonymous'].permissions=p
        self.instance.schema_hook = hook
        self._handle_mail(message)
        m = self.db.user.list()
        m.sort()
        self.assertNotEqual(l, m)

    def testNewUserAuthorHighBit(self):
        l = set(self.db.user.list())
        # From: name has Euro symbol in it
        message = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: =?utf8?b?SOKCrGxsbw==?= <fubar@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
'''
        def hook (db, **kw):
            ''' set up callback for db open '''
            p = [
                db.security.getPermission('Create', 'user'),
                db.security.getPermission('Email Access', None),
            ]
            db.security.role['anonymous'].permissions=p
        self.instance.schema_hook = hook
        self._handle_mail(message)
        m = set(self.db.user.list())
        new = list(m - l)[0]
        name = self.db.user.get(new, 'realname')
        self.assertEquals(name, 'H€llo')

    def testUnknownUser(self):
        l = set(self.db.user.list())
        message = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Nonexisting User <nonexisting@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing nonexisting user...

This is a test submission of a new issue.
'''
        self.db.close()
        handler = self.instance.MailGW(self.instance)
        # we want a bounce message:
        handler.trapExceptions = 1
        ret = handler.main(StringIO(message))
        self.compareMessages(self._get_mail(),
'''FROM: Roundup issue tracker <roundup-admin@your.tracker.email.domain.example>
TO: nonexisting@bork.bork.bork
From nobody Tue Jul 14 12:04:11 2009
Content-Type: multipart/mixed; boundary="===============0639262320=="
MIME-Version: 1.0
Subject: Failed issue tracker submission
To: nonexisting@bork.bork.bork
From: Roundup issue tracker <roundup-admin@your.tracker.email.domain.example>
Date: Tue, 14 Jul 2009 12:04:11 +0000
Precedence: bulk
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Version: 1.4.8
MIME-Version: 1.0

--===============0639262320==
Content-Type: text/plain; charset="us-ascii"
MIME-Version: 1.0
Content-Transfer-Encoding: 7bit



You are not a registered user.

Unknown address: nonexisting@bork.bork.bork

--===============0639262320==
Content-Type: text/plain; charset="us-ascii"
MIME-Version: 1.0
Content-Transfer-Encoding: 7bit

Content-Type: text/plain;
  charset="iso-8859-1"
From: Nonexisting User <nonexisting@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing nonexisting user...

This is a test submission of a new issue.

--===============0639262320==--
''')

    def testEnc01(self):
        self.doNewIssue()
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: text/plain;
        charset="iso-8859-1"
Content-Transfer-Encoding: quoted-printable

A message with encoding (encoded oe =F6)

''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test.test> added the comment:

A message with encoding (encoded oe =C3=B6)

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testEncNonUTF8(self):
        self.doNewIssue()
        self.instance.config.EMAIL_CHARSET = 'iso-8859-1'
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: text/plain;
        charset="iso-8859-1"
Content-Transfer-Encoding: quoted-printable

A message with encoding (encoded oe =F6)

''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="iso-8859-1"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test.test> added the comment:

A message with encoding (encoded oe =F6)

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')


    def testMultipartEnc01(self):
        self.doNewIssue()
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: mary <mary@test.test>
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
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test.test> added the comment:

A message with first part encoded (encoded oe =C3=B6)

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testContentDisposition(self):
        self.doNewIssue()
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: multipart/mixed; boundary="bCsyhTFzCvuiizWE"
Content-Disposition: inline


--bCsyhTFzCvuiizWE
Content-Type: text/plain; charset=us-ascii
Content-Disposition: inline

test attachment binary

--bCsyhTFzCvuiizWE
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="main.dvi"
Content-Transfer-Encoding: base64

SnVzdCBhIHRlc3QgAQo=

--bCsyhTFzCvuiizWE--
''')
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        file = self.db.file.getnode (self.db.msg.get(messages[-1], 'files')[0])
        self.assertEqual(file.name, 'main.dvi')
        self.assertEqual(file.content, 'Just a test \001\n')

    def testFollowupStupidQuoting(self):
        self.doNewIssue()

        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: Re: "[issue1] Testing... "

This is a followup
''')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


richard <richard@test.test> added the comment:

This is a followup

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
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

        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
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
        # figure the new message id
        newmessages = self.db.issue.get(nodeid, 'messages')
        for msg in messages:
            newmessages.remove(msg)
        messageid = newmessages[0]

        self.compareMessages(self.db.msg.get(messageid, 'content'), expect)

    def testUserLookup(self):
        i = self.db.user.create(username='user1', address='user1@foo.com')
        self.assertEqual(uidFromAddress(self.db, ('', 'user1@foo.com'), 0), i)
        self.assertEqual(uidFromAddress(self.db, ('', 'USER1@foo.com'), 0), i)
        i = self.db.user.create(username='user2', address='USER2@foo.com')
        self.assertEqual(uidFromAddress(self.db, ('', 'USER2@foo.com'), 0), i)
        self.assertEqual(uidFromAddress(self.db, ('', 'user2@foo.com'), 0), i)

    def testUserAlternateLookup(self):
        i = self.db.user.create(username='user1', address='user1@foo.com',
                                alternate_addresses='user1@bar.com')
        self.assertEqual(uidFromAddress(self.db, ('', 'user1@bar.com'), 0), i)
        self.assertEqual(uidFromAddress(self.db, ('', 'USER1@bar.com'), 0), i)

    def testUserCreate(self):
        i = uidFromAddress(self.db, ('', 'user@foo.com'), 1)
        self.assertNotEqual(uidFromAddress(self.db, ('', 'user@bar.com'), 1), i)

    def testRFC2822(self):
        ascii_header = "[issue243] This is a \"test\" - with 'quotation' marks"
        unicode_header = '[issue244] \xd0\xb0\xd0\xbd\xd0\xb4\xd1\x80\xd0\xb5\xd0\xb9'
        unicode_encoded = '=?utf-8?q?[issue244]_=D0=B0=D0=BD=D0=B4=D1=80=D0=B5=D0=B9?='
        self.assertEqual(rfc2822.encode_header(ascii_header), ascii_header)
        self.assertEqual(rfc2822.encode_header(unicode_header), unicode_encoded)

    def testRegistrationConfirmation(self):
        otk = "Aj4euk4LZSAdwePohj90SME5SpopLETL"
        self.db.getOTKManager().set(otk, username='johannes')
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Message-Id: <dummy_test_message_id>
Subject: Re: Complete your registration to Roundup issue tracker
 -- key %s

This is a test confirmation of registration.
''' % otk)
        self.db.user.lookup('johannes')

    def testFollowupOnNonIssue(self):
        self.db.keyword.create(name='Foo')
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [keyword1] Testing... [name=Bar]

''')
        self.assertEqual(self.db.keyword.get('1', 'name'), 'Bar')

    def testResentFrom(self):
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
Resent-From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
''')
        assert not os.path.exists(SENDMAILDEBUG)
        l = self.db.issue.get(nodeid, 'nosy')
        l.sort()
        self.assertEqual(l, [self.richard_id, self.mary_id])
        return nodeid

    def testDejaVu(self):
        self.assertRaises(IgnoreLoop, self._handle_mail,
            '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
X-Roundup-Loop: hello
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Message-Id: <dummy_test_message_id>
Subject: Re: [issue] Testing...

Hi, I've been mis-configured to loop messages back to myself.
''')

    def testItsBulkStupid(self):
        self.assertRaises(IgnoreBulk, self._handle_mail,
            '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
Precedence: bulk
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Message-Id: <dummy_test_message_id>
Subject: Re: [issue] Testing...

Hi, I'm on holidays, and this is a dumb auto-responder.
''')

    def testAutoReplyEmailsAreIgnored(self):
        self.assertRaises(IgnoreBulk, self._handle_mail,
            '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Message-Id: <dummy_test_message_id>
Subject: Re: [issue] Out of office AutoReply: Back next week

Hi, I am back in the office next week
''')

    def testNoSubject(self):
        self.assertRaises(MailUsageError, self._handle_mail,
            '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')

    #
    # TEST FOR INVALID DESIGNATOR HANDLING
    #
    def testInvalidDesignator(self):
        self.assertRaises(MailUsageError, self._handle_mail,
            '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: [frobulated] testing
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        self.assertRaises(MailUsageError, self._handle_mail,
            '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: [issue12345] testing
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')

    def testInvalidClassLoose(self):
        self.instance.config.MAILGW_SUBJECT_PREFIX_PARSING = 'loose'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: [frobulated] testing
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'),
            '[frobulated] testing')

    def testInvalidClassLooseReply(self):
        self.instance.config.MAILGW_SUBJECT_PREFIX_PARSING = 'loose'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: Re: [frobulated] testing
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'),
            '[frobulated] testing')

    def testInvalidClassLoose(self):
        self.instance.config.MAILGW_SUBJECT_PREFIX_PARSING = 'loose'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: [issue1234] testing
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'),
            '[issue1234] testing')

    def testClassLooseOK(self):
        self.instance.config.MAILGW_SUBJECT_PREFIX_PARSING = 'loose'
        self.db.keyword.create(name='Foo')
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: [keyword1] Testing... [name=Bar]
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.keyword.get('1', 'name'), 'Bar')

    def testClassStrictInvalid(self):
        self.instance.config.MAILGW_SUBJECT_PREFIX_PARSING = 'strict'
        self.instance.config.MAILGW_DEFAULT_CLASS = ''

        message = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: Testing...
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

'''
        self.assertRaises(MailUsageError, self._handle_mail, message)

    def testClassStrictValid(self):
        self.instance.config.MAILGW_SUBJECT_PREFIX_PARSING = 'strict'
        self.instance.config.MAILGW_DEFAULT_CLASS = ''

        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: [issue] Testing...
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')

        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'), 'Testing...')

    #
    # TEST FOR INVALID COMMANDS HANDLING
    #
    def testInvalidCommands(self):
        self.assertRaises(MailUsageError, self._handle_mail,
            '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: testing [frobulated]
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')

    def testInvalidCommandPassthrough(self):
        self.instance.config.MAILGW_SUBJECT_SUFFIX_PARSING = 'none'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: testing [frobulated]
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'),
            'testing [frobulated]')

    def testInvalidCommandPassthroughLoose(self):
        self.instance.config.MAILGW_SUBJECT_SUFFIX_PARSING = 'loose'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: testing [frobulated]
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'),
            'testing [frobulated]')

    def testInvalidCommandPassthroughLooseOK(self):
        self.instance.config.MAILGW_SUBJECT_SUFFIX_PARSING = 'loose'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: testing [assignedto=mary]
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'), 'testing')
        self.assertEqual(self.db.issue.get(nodeid, 'assignedto'), self.mary_id)

    def testCommandDelimiters(self):
        self.instance.config.MAILGW_SUBJECT_SUFFIX_DELIMITERS = '{}'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: testing {assignedto=mary}
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'), 'testing')
        self.assertEqual(self.db.issue.get(nodeid, 'assignedto'), self.mary_id)

    def testPrefixDelimiters(self):
        self.instance.config.MAILGW_SUBJECT_SUFFIX_DELIMITERS = '{}'
        self.db.keyword.create(name='Foo')
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: {keyword1} Testing... {name=Bar}

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.keyword.get('1', 'name'), 'Bar')

    def testCommandDelimitersIgnore(self):
        self.instance.config.MAILGW_SUBJECT_SUFFIX_DELIMITERS = '{}'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: testing [assignedto=mary]
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'),
            'testing [assignedto=mary]')
        self.assertEqual(self.db.issue.get(nodeid, 'assignedto'), None)

    def testReplytoMatch(self):
        self.instance.config.MAILGW_SUBJECT_PREFIX_PARSING = 'loose'
        nodeid = self.doNewIssue()
        nodeid2 = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id2>
In-Reply-To: <dummy_test_message_id>
Subject: Testing...

Followup message.
''')

        nodeid3 = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id3>
In-Reply-To: <dummy_test_message_id2>
Subject: Testing...

Yet another message in the same thread/issue.
''')

        self.assertEqual(nodeid, nodeid2)
        self.assertEqual(nodeid, nodeid3)

    def testHelpSubject(self):
        message = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id2>
In-Reply-To: <dummy_test_message_id>
Subject: hElp


'''
        self.assertRaises(MailUsageHelp, self._handle_mail, message)

    def testMaillistSubject(self):
        self.instance.config.MAILGW_SUBJECT_SUFFIX_DELIMITERS = '[]'
        self.db.keyword.create(name='Foo')
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: [mailinglist-name] [keyword1] Testing.. [name=Bar]
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')

        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.keyword.get('1', 'name'), 'Bar')

    def testUnknownPrefixSubject(self):
        self.db.keyword.create(name='Foo')
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: VeryStrangeRe: [keyword1] Testing.. [name=Bar]
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')

        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.keyword.get('1', 'name'), 'Bar')

    def testIssueidLast(self):
        nodeid1 = self.doNewIssue()
        nodeid2 = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: New title [issue1]

This is a second followup
''')

        assert nodeid1 == nodeid2
        self.assertEqual(self.db.issue.get(nodeid2, 'title'), "Testing...")


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(MailgwTestCase))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: set filetype=python sts=4 sw=4 et si :
