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

# TODO: test bcc

import email
from . import gpgmelib
import unittest, tempfile, os, shutil, errno, sys, difflib, time, io

import pytest

try:
    import gpg, gpg.core
    skip_pgp = lambda func, *args, **kwargs: func
except ImportError:
    # FIX: workaround for a bug in pytest.mark.skip():
    #   https://github.com/pytest-dev/pytest/issues/568
    from .pytest_patcher import mark_class
    skip_pgp = mark_class(pytest.mark.skip(
        reason="Skipping PGP tests: 'gpg' not installed"))


from roundup.anypy.email_ import message_from_bytes
from roundup.anypy.strings import b2s, u2s, s2b

if 'SENDMAILDEBUG' not in os.environ:
    os.environ['SENDMAILDEBUG'] = 'mail-test.log'
SENDMAILDEBUG = os.environ['SENDMAILDEBUG']

from roundup import mailgw, i18n, roundupdb
from roundup.mailgw import MailGW, Unauthorized, uidFromAddress, \
    parseContent, IgnoreLoop, IgnoreBulk, MailUsageError, MailUsageHelp
from roundup import init, instance, password, __version__

#import db_test_base
from roundup.test import memorydb
from .cmp_helper import StringFragmentCmpHelper

def expectedFailure(method):
    """ For marking a failing test.
        This will *not* run the test and return success instead.
    """
    return lambda x: 0


def get_body(message):
    if not message.is_multipart():
        return message.get_payload()

    return message.as_string().split('\n\n', 1)[-1]

def unfold(lst):
    return [l.replace('\n', '') for l in lst]


class Tracker(object):
    def open(self, journaltag):
        return self.db

class DiffHelper:
    def compareMessages(self, new, old):
        """Compare messages for semantic equivalence.

        Only use this for full rfc 2822/822/whatever messages with headers.

        Will raise an AssertionError with a diff for inequality.

        Note that header fieldnames are case-insensitive.
        So if a header fieldname appears more than once in different casing
        and the values are not equal, there will be more than one entry
        in the diff. Typical examples are "From:"/ "FROM:" and "TO:"/"To:".
        """
        new = email.message_from_string(new.strip())
        old = email.message_from_string(old.strip())

        # all Roundup-generated messages have "Precedence: bulk"
        if 'Precedence' not in old:
            old['Precedence'] = 'bulk'

        # don't try to compare the date
        del new['date'], old['date']

        if not new == old:
            res = []

            replace = {}

            # make sure that all headers are the same between the new
            # and old (reference) messages. Once we have done this we
            # can iterate over all the headers in the new message and
            # compare contents. If we don't do this, we don't know
            # when the new message has dropped a header that should be
            # present.
            # Headers are case insensitive, so smash to lower case
            new_headers=[x.lower() for x in new.keys()]
            old_headers=[x.lower() for x in old.keys()]

            if "x-roundup-version" not in old_headers:
                # add it. it is skipped in most cases and missing from
                # the test cases in old.
                old_headers.append("x-roundup-version")
                
            new_headers.sort() # sort, make comparison easier in error message.
            old_headers.sort()

            if new_headers != old_headers:
                res.append('headers differ new vs. reference: %r != %r'%(new_headers, old_headers))
                
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
                    newmimeboundary = new[key].split('=',1)[-1].strip('"')
                    oldmimeboundary = old.get(key, '').split('=',1)[-1].strip('"')
                    # mime types are not case sensitive rfc 2045
                    newmimetype = new[key].split(';',1)[0].strip('"').lower()
                    oldmimetype = old.get(key, '').split(';',1)[0].strip('"').lower()
                    # throw an error if we have differeing content types
                    if not newmimetype == oldmimetype:
                        res.append('content-type mime type headers differ new vs. reference: %r != %r'%(newmimetype, oldmimetype))
                    replace ['--' + newmimeboundary] = '--' + oldmimeboundary
                    replace ['--' + newmimeboundary + '--'] = '--' + oldmimeboundary + '--'
                elif unfold(new.get_all(key, '')) != unfold(old.get_all(key, '')):
                    # check that all other headers are identical, including
                    # headers that appear more than once.
                    res.append('  %s: %r != %r' % (key, old.get_all(key, ''),
                        new.get_all(key, '')))

            # TODO replace the string comparision with a mimepart comparison
            body_diff = self.compareStrings(get_body(new), get_body(old),
                replace=replace)
            if body_diff:
                res.append('')
                res.extend(body_diff)

            if res:
                res.insert(0, 'Generated message not correct (diff follows, expected vs. actual):')
                raise AssertionError('\n'.join(res))

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

from roundup.hyperdb import String


class MailgwTestAbstractBase(DiffHelper):
    count = 0
    schema = 'classic'
    def setUp(self):
        self.old_translate_ = mailgw._
        roundupdb._ = mailgw._ = i18n.get_translation(language='C').gettext
        self.__class__.count = self.__class__.count + 1

        # and open the database / "instance"
        self.db = memorydb.create('admin')

        self.db.issue.addprop(tx_Source=String())
        self.db.msg.addprop(tx_Source=String())
        self.db.post_init()

        self.db.tx_Source = "email"

        self.instance = Tracker()
        self.instance.db = self.db
        self.instance.config = self.db.config
        self.instance.MailGW = MailGW

        self.chef_id = self.db.user.create(username='Chef',
            address='chef@bork.bork.bork', realname='Bork, Chef', roles='User')
        self.richard_id = self.db.user.create(username='richard',
            address='richard@test.test', roles='User')
        self.mary_id = self.db.user.create(username='mary',
            address='mary@test.test', roles='User', realname='Contrary, Mary')
        self.john_id = self.db.user.create(username='john',
            address='john@test.test', roles='User', realname='John Doe',
            alternate_addresses='jondoe@test.test\njohn.doe@test.test')
        self.rgg_id = self.db.user.create(username='rgg',
            address='rgg@test.test', roles='User')

    def tearDown(self):
        roundupdb._ = mailgw._ = self.old_translate_
        if os.path.exists(SENDMAILDEBUG):
            os.remove(SENDMAILDEBUG)
        self.db.close()
        memorydb.db_nuke('')

    def _allowAnonymousSubmit(self):
        p = [
            self.db.security.getPermission('Register', 'user'),
            self.db.security.getPermission('Email Access', None),
            self.db.security.getPermission('Create', 'issue'),
            self.db.security.getPermission('Create', 'msg'),
        ]
        self.db.security.role['anonymous'].permissions = p

    def _create_mailgw(self, message, args=()):
        class MailGW(self.instance.MailGW):
            def handle_message(self, message):
                return self._handle_message(message)
        handler = MailGW(self.instance, args)
        handler.db = self.db
        return handler

    def _handle_mail(self, message, args=(), trap_exc=0):
        handler = self._create_mailgw(message, args)
        handler.trapExceptions = trap_exc
        return handler.main(io.BytesIO(s2b(message)))

    def _get_mail(self):
        """Reads an email that has been written to file via debug output.

        Note: the resulting email will have three leading extra lines
        written by the self.debug code branch in Mailer.smtp_send().
        """
        f = open(SENDMAILDEBUG)
        try:
            return f.read()
        finally:
            f.close()

    def testHelpMessage(self):
        help_message='''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>
Subject: help

'''
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertRaises(MailUsageHelp, self._handle_mail, help_message)
        # FIXME I think help sends email. but using _get_mail() doesn't
        # work. The file mail-test.log is missing.
        # self.compareMessages(self._get_mail(), 1)


    # Normal test-case used for both non-pgp test and a test while pgp
    # is enabled, so this test is run in both test suites.
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
        self.assertEqual(self.db.issue.get(nodeid, 'tx_Source'), 'email')


class MailgwTestCase(MailgwTestAbstractBase, StringFragmentCmpHelper, unittest.TestCase):

    def testTextHtmlMessage(self):
        html_message='''Content-Type: text/html;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

<body>
<script>
this must not be in output
</script>
<style>
p {display:block}
</style>
    <div class="header"><h1>Roundup</h1>
        <div id="searchbox" style="display: none">
          <form class="search" action="../search.html" method="get">
            <input type="text" name="q" size="18" />
            <input type="submit" value="Search" />
            <input type="hidden" name="check_keywords" value="yes" />
            <input type="hidden" name="area" value="default" />
          </form>
        </div>
        <script type="text/javascript">$('#searchbox').show(0);</script>
    </div>
       <ul class="current">
<li class="toctree-l1"><a class="reference internal" href="../index.html">Home</a></li>
<li class="toctree-l1"><a class="reference external" href="http://pypi.python.org/pypi/roundup">Download</a></li>
<li class="toctree-l1 current"><a class="reference internal" href="../docs.html">Docs</a><ul class="current">
<li class="toctree-l2"><a class="reference internal" href="features.html">Roundup Features</a></li>
<li class="toctree-l2 current"><a class="current reference internal" href="">Installing Roundup</a></li>
<li class="toctree-l2"><a class="reference internal" href="upgrading.html">Upgrading to newer versions of Roundup</a></li>
<li class="toctree-l2"><a class="reference internal" href="FAQ.html">Roundup FAQ</a></li>
<li class="toctree-l2"><a class="reference internal" href="user_guide.html">User Guide</a></li>
<li class="toctree-l2"><a class="reference internal" href="customizing.html">Customising Roundup</a></li>
<li class="toctree-l2"><a class="reference internal" href="admin_guide.html">Administration Guide</a></li>
</ul>
<div class="section" id="prerequisites">
<h2><a class="toc-backref" href="#id5">Prerequisites</a></h2>
<p>Roundup requires Python 2.6 or newer (but not Python 3) with a functioning
anydbm module. Download the latest version from <a class="reference external" href="http://www.python.org/">http://www.python.org/</a>.
It is highly recommended that users install the latest patch version
of python as these contain many fixes to serious bugs.</p>
<p>Some variants of Linux will need an additional &#8220;python dev&#8221; package
installed for Roundup installation to work. Debian and derivatives, are
known to require this.</p>
<p>If you&#8217;re on windows, you will either need to be using the ActiveState python
distribution (at <a class="reference external" href="http://www.activestate.com/Products/ActivePython/">http://www.activestate.com/Products/ActivePython/</a>), or you&#8217;ll
have to install the win32all package separately (get it from
<a class="reference external" href="http://starship.python.net/crew/mhammond/win32/">http://starship.python.net/crew/mhammond/win32/</a>).</p>
</div>
</body>
'''
        text_fragments = ['Roundup\n        Home\nDownload\nDocs\nRoundup Features\nInstalling Roundup\nUpgrading to newer versions of Roundup\nRoundup FAQ\nUser Guide\nCustomising Roundup\nAdministration Guide\nPrerequisites\n\nRoundup requires Python 2.6 or newer (but not Python 3) with a functioning\nanydbm module. Download the latest version from http://www.python.org/.\nIt is highly recommended that users install the latest patch version\nof python as these contain many fixes to serious bugs.\n\nSome variants of Linux will need an additional ', ('python dev', u2s(u'\u201cpython dev\u201d')), ' package\ninstalled for Roundup installation to work. Debian and derivatives, are\nknown to require this.\n\nIf you', (u2s(u'\u2019'), ''), 're on windows, you will either need to be using the ActiveState python\ndistribution (at http://www.activestate.com/Products/ActivePython/), or you', (u2s(u'\u2019'), ''), 'll\nhave to install the win32all package separately (get it from\nhttp://starship.python.net/crew/mhammond/win32/).']

        self.db.config.MAILGW_CONVERT_HTMLTOTEXT = "dehtml"
        nodeid = self._handle_mail(html_message)
        assert not os.path.exists(SENDMAILDEBUG)
        msgid = self.db.issue.get(nodeid, 'messages')[0]
        self.compareStringFragments(self.db.msg.get(msgid, 'content'),
                                    text_fragments)

        self.db.config.MAILGW_CONVERT_HTMLTOTEXT = "none"
        self.assertRaises(MailUsageError, self._handle_mail, html_message)

    def testMessageWithFromInIt(self):
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

From here to there!
''')
        assert not os.path.exists(SENDMAILDEBUG)
        msgid = self.db.issue.get(nodeid, 'messages')[0]
        self.assertEqual(self.db.msg.get(msgid, 'content'), 'From here to there!')

    def testNoMessageId(self):
        self.instance.config['MAIL_DOMAIN'] = 'example.com'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Subject: [issue] Testing...

Hi there!
''')
        assert not os.path.exists(SENDMAILDEBUG)
        msgid = self.db.issue.get(nodeid, 'messages')[0]
        messageid = self.db.msg.get(msgid, 'messageid')
        x1, x2 = messageid.split('@')
        self.assertEqual(x2, 'example.com>')
        x = x1.split('.')[-1]
        self.assertEqual(x, 'issueNone')
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: [issue%(nodeid)s] Testing...

Just a test reply
'''%locals())
        msgid = self.db.issue.get(nodeid, 'messages')[-1]
        messageid = self.db.msg.get(msgid, 'messageid')
        x1, x2 = messageid.split('@')
        self.assertEqual(x2, 'example.com>')
        x = x1.split('.')[-1]
        self.assertEqual(x, "issue%s"%nodeid)

    def testOptions(self):
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Reply-To: chef@bork.bork.bork
Subject: [issue] Testing...

Hi there!
''', (('-C', 'issue'), ('-S', 'status=chatting;priority=critical')))
        self.assertEqual(self.db.issue.get(nodeid, 'status'), '3')
        self.assertEqual(self.db.issue.get(nodeid, 'priority'), '1')

    def testOptionsMulti(self):
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Reply-To: chef@bork.bork.bork
Subject: [issue] Testing...

Hi there!
''', (('-C', 'issue'), ('-S', 'status=chatting'), ('-S', 'priority=critical')))
        self.assertEqual(self.db.issue.get(nodeid, 'status'), '3')
        self.assertEqual(self.db.issue.get(nodeid, 'priority'), '1')

    def testOptionClass(self):
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Reply-To: chef@bork.bork.bork
Subject: [issue] Testing... [status=chatting;priority=critical]

Hi there!
''', (('-c', 'issue'),))
        self.assertEqual(self.db.issue.get(nodeid, 'title'), 'Testing...')
        self.assertEqual(self.db.issue.get(nodeid, 'status'), '3')
        self.assertEqual(self.db.issue.get(nodeid, 'priority'), '1')

    newmsg = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing...

This is a test submission of a new issue.
'''

    def doNewIssue(self):
        nodeid = self._handle_mail(self.newmsg)
        assert not os.path.exists(SENDMAILDEBUG)
        l = self.db.issue.get(nodeid, 'nosy')
        l.sort()
        self.assertEqual(l, [self.chef_id, self.richard_id])

        # check that the message has the right source code
        l = self.db.msg.get('1', 'tx_Source')
        self.assertEqual(l, 'email')

        return nodeid

    def testNewIssue(self):
        self.doNewIssue()

    def testNewIssueNosy(self):
        self.instance.config.ADD_AUTHOR_TO_NOSY = 'yes'
        nodeid = self.doNewIssue()
        m = self.db.issue.get(nodeid, 'messages')
        self.assertEqual(len(m), 1)
        recv = self.db.msg.get(m[0], 'recipients')
        self.assertEqual(recv, [self.richard_id])

    def testNewIssueNosyAuthor(self):
        self.instance.config.ADD_AUTHOR_TO_NOSY = 'no'
        self.instance.config.MESSAGES_TO_AUTHOR = 'nosy'
        nodeid = self._handle_mail(self.newmsg)
        assert not os.path.exists(SENDMAILDEBUG)
        l = self.db.issue.get(nodeid, 'nosy')
        l.sort()
        self.assertEqual(l, [self.richard_id])
        m = self.db.issue.get(nodeid, 'messages')
        self.assertEqual(len(m), 1)
        recv = self.db.msg.get(m[0], 'recipients')
        recv.sort()
        self.assertEqual(recv, [self.richard_id])

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
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
X-Roundup-Issue-Id: 1
Content-Transfer-Encoding: quoted-printable


New submission from Bork, Chef <chef@bork.bork.bork>:

This is a test submission of a new issue.

----------
assignedto: richard
messages: 1
nosy: Chef, mary, richard
status: unread
title: Testing...
tx_Source: email

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
TO: mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
X-Roundup-Issue-Id: 1
Content-Transfer-Encoding: quoted-printable

This is a test submission of a new issue.

----------
assignedto: richard
messages: 1
nosy: Chef, mary, richard
status: unread
title: Testing...
tx_Source: email

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
TO: mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
X-Roundup-Issue-Id: 1
Content-Transfer-Encoding: quoted-printable

New submission from Bork, Chef:

This is a test submission of a new issue.

----------
assignedto: richard
messages: 1
nosy: Chef, mary, richard
status: unread
title: Testing...
tx_Source: email

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    octetstream_msg = '''From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: multipart/mixed; boundary="uh56ypi7view24rr"
Content-Disposition: inline

--uh56ypi7view24rr
Content-Type: text/plain; charset=us-ascii
Content-Disposition: inline

Attach a file with non-ascii characters in it (encoded latin-1 should
make it as-is through roundup due to Content-Type
application/octet-stream)
-- 
Ralf Schlatterbeck             email: ralf@zoo.priv.at

--uh56ypi7view24rr
Content-Type: application/octet-stream
Content-Disposition: attachment; filename=testfile
Content-Transfer-Encoding: quoted-printable

This is a file containing text
in latin-1 format =E4=F6=FC=C4=D6=DC=DF

--uh56ypi7view24rr--
'''

    filename_msg = '''From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: multipart/mixed; boundary="uh56ypi7view24rr"
Content-Disposition: inline

--uh56ypi7view24rr
Content-Type: text/plain; charset=us-ascii
Content-Disposition: inline

Attach a file with non-ascii characters in it (encoded latin-1 should
make it as-is through roundup due to Content-Type
application/octet-stream)
-- 
Ralf Schlatterbeck             email: ralf@zoo.priv.at

--uh56ypi7view24rr
Content-Type: application/octet-stream
Content-Disposition: attachment;
    filename==?iso-8859-1?Q?20210312=5FM=FCnchen=5FRepor?=
    =?iso-8859-1?Q?t.pdf?=
Content-Transfer-Encoding: quoted-printable

This is a file containing text
in latin-1 format =E4=F6=FC=C4=D6=DC=DF

--uh56ypi7view24rr--
'''

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

    multipart_msg_latin1 = '''From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: multipart/alternative; boundary=001485f339f8f361fb049188dbba


--001485f339f8f361fb049188dbba
Content-Type: text/plain; charset=ISO-8859-1
Content-Transfer-Encoding: quoted-printable

umlaut =E4=F6=FC=C4=D6=DC=DF

--001485f339f8f361fb049188dbba
Content-Type: text/html; charset=ISO-8859-1
Content-Transfer-Encoding: quoted-printable

<html>umlaut =E4=F6=FC=C4=D6=DC=DF</html>

--001485f339f8f361fb049188dbba--
'''

    multipart_msg_rfc822 = '''From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: multipart/mixed; boundary=001485f339f8f361fb049188dbba

This is a multi-part message in MIME format.
--001485f339f8f361fb049188dbba
Content-Type: text/plain; charset=ISO-8859-15
Content-Transfer-Encoding: 7bit

First part: Text

--001485f339f8f361fb049188dbba
Content-Type: message/rfc822; name="Fwd: Original email subject.eml"
Content-Transfer-Encoding: 7bit
Content-Disposition: attachment; filename="Fwd: Original email subject.eml"

Message-Id: <followup_dummy_id_2>
In-Reply-To: <dummy_test_message_id_2>
MIME-Version: 1.0
Subject: Fwd: Original email subject
Date: Mon, 23 Aug 2010 08:23:33 +0200
Content-Type: multipart/alternative; boundary="090500050101020406060002"

This is a multi-part message in MIME format.
--090500050101020406060002
Content-Type: text/plain; charset=ISO-8859-15; format=flowed
Content-Transfer-Encoding: 7bit

some text in inner email
========================

--090500050101020406060002
Content-Type: text/html; charset=ISO-8859-15
Content-Transfer-Encoding: 7bit

<html>
some text in inner email
========================
</html>

--090500050101020406060002--

--001485f339f8f361fb049188dbba--
'''

    def testOctetStreamTranscoding(self):
        self.doNewIssue()
        self._handle_mail(self.octetstream_msg)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        assert(len(msg.files) == 1)
        names = {0 : 'testfile'}
        content = [b'''This is a file containing text
in latin-1 format \xE4\xF6\xFC\xC4\xD6\xDC\xDF
''']
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, names.get (n, 'unnamed'))
            self.assertEqual(f.binary_content, content [n])

    def testFileAttachWithUmlaut(self):
        self.doNewIssue()
        self._handle_mail(self.filename_msg)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        assert(len(msg.files) == 1)
        names = {0 : u'20210312_M\xfcnchen_Report.pdf'}
        content = [b'''This is a file containing text
in latin-1 format \xE4\xF6\xFC\xC4\xD6\xDC\xDF
''']
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, names.get (n, 'unnamed'))
            self.assertEqual(f.binary_content, content [n])

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

    def testMultipartSeveralAttachmentMessages(self):
        self.doNewIssue()
        self._handle_mail(self.multipart_msg)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        self.assertEqual(messages[-1], '2')
        msg = self.db.msg.getnode (messages[-1])
        self.assertEqual(len(msg.files), 5)
        issue = self.db.issue.getnode ('1')
        self.assertEqual(len(issue.files), 5)
        names = {0 : 'first.dvi', 4 : 'second.dvi'}
        content = {3 : 'test attachment third text/plain\n',
                   4 : 'Just a test\n'}
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, names.get (n, 'unnamed'))
            if n in content :
                self.assertEqual(f.content, content [n])
        self.assertEqual(msg.content, 'test attachment second text/plain')
        self.assertEqual(msg.files, ['1', '2', '3', '4', '5'])
        self.assertEqual(issue.files, ['1', '2', '3', '4', '5'])

        self._handle_mail(self.multipart_msg)
        issue = self.db.issue.getnode ('1')
        self.assertEqual(len(issue.files), 10)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        self.assertEqual(messages[-1], '3')
        msg = self.db.msg.getnode (messages[-1])
        self.assertEqual(issue.files, [str(i+1) for i in range(10)])
        self.assertEqual(msg.files, ['6', '7', '8', '9', '10'])

    def testMultipartKeepFiles(self):
        self.doNewIssue()
        self._handle_mail(self.multipart_msg)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        self.assertEqual(len(msg.files), 5)
        issue = self.db.issue.getnode ('1')
        self.assertEqual(len(issue.files), 5)
        names = {0 : 'first.dvi', 4 : 'second.dvi'}
        content = {3 : 'test attachment third text/plain\n',
                   4 : 'Just a test\n'}
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, names.get (n, 'unnamed'))
            if n in content :
                self.assertEqual(f.content, content [n])
        self.assertEqual(msg.content, 'test attachment second text/plain')
        self._handle_mail('''From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id2>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This ist a message without attachment
''')
        issue = self.db.issue.getnode ('1')
        self.assertEqual(len(issue.files), 5)
        self.assertEqual(issue.files, ['1', '2', '3', '4', '5'])

    def testMultipartDropAlternatives(self):
        self.doNewIssue()
        self.db.config.MAILGW_IGNORE_ALTERNATIVES = True
        self._handle_mail(self.multipart_msg)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        self.assertEqual(len(msg.files), 2)
        names = {1 : 'second.dvi'}
        content = {0 : 'test attachment third text/plain\n',
                   1 : 'Just a test\n'}
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, names.get (n, 'unnamed'))
            if n in content :
                self.assertEqual(f.content, content [n])
        self.assertEqual(msg.content, 'test attachment second text/plain')

    def testMultipartCharsetUTF8NoAttach(self):
        c = b2s(b'umlaut \xc3\xa4\xc3\xb6\xc3\xbc\xc3\x84\xc3\x96\xc3\x9c\xc3\x9f')
        self.doNewIssue()
        self.db.config.NOSY_MAX_ATTACHMENT_SIZE = 0
        self._handle_mail(self.multipart_msg_latin1)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        self.assertEqual(len(msg.files), 1)
        name = 'unnamed'
        content = '<html>' + c + '</html>\n'
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, name)
            self.assertEqual(f.content, content)
        self.assertEqual(msg.content, c)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
X-Roundup-Issue-Files: unnamed
X-Roundup-Issue-Id: 1
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test.test> added the comment:

umlaut =C3=A4=C3=B6=C3=BC=C3=84=C3=96=C3=9C=C3=9F
File 'unnamed' not attached - you can download it from http://tracker.examp=
le/cgi-bin/roundup.cgi/bugs/file1.

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testMultipartCharsetLatin1NoAttach(self):
        c = b2s(b'umlaut \xc3\xa4\xc3\xb6\xc3\xbc\xc3\x84\xc3\x96\xc3\x9c\xc3\x9f')
        self.doNewIssue()
        self.db.config.NOSY_MAX_ATTACHMENT_SIZE = 0
        self.db.config.MAIL_CHARSET = 'iso-8859-1'
        self._handle_mail(self.multipart_msg_latin1)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        self.assertEqual(len(msg.files), 1)
        name = 'unnamed'
        content = '<html>' + c + '</html>\n'
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, name)
            self.assertEqual(f.content, content)
        self.assertEqual(msg.content, c)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="iso-8859-1"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
X-Roundup-Issue-Files: unnamed
X-Roundup-Issue-Id: 1
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test.test> added the comment:

umlaut =E4=F6=FC=C4=D6=DC=DF
File 'unnamed' not attached - you can download it from http://tracker.examp=
le/cgi-bin/roundup.cgi/bugs/file1.

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testMultipartCharsetUTF8AttachFile(self):
        c = b2s(b'umlaut \xc3\xa4\xc3\xb6\xc3\xbc\xc3\x84\xc3\x96\xc3\x9c\xc3\x9f')
        self.doNewIssue()
        self._handle_mail(self.multipart_msg_latin1)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        self.assertEqual(len(msg.files), 1)
        name = 'unnamed'
        content = '<html>' + c + '</html>\n'
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, name)
            self.assertEqual(f.content, content)
        self.assertEqual(msg.content, c)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: multipart/mixed; boundary="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
X-Roundup-Issue-Files: unnamed
X-Roundup-Issue-Id: 1


--utf-8
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test.test> added the comment:

umlaut =C3=A4=C3=B6=C3=BC=C3=84=C3=96=C3=9C=C3=9F

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
--utf-8
Content-Type: text/html
MIME-Version: 1.0
Content-Transfer-Encoding: base64
Content-Disposition: attachment;
 filename="unnamed"

PGh0bWw+dW1sYXV0IMOkw7bDvMOEw5bDnMOfPC9odG1sPgo=

--utf-8--
''')

    def testMultipartCharsetLatin1AttachFile(self):
        c = b2s(b'umlaut \xc3\xa4\xc3\xb6\xc3\xbc\xc3\x84\xc3\x96\xc3\x9c\xc3\x9f')
        self.doNewIssue()
        self.db.config.MAIL_CHARSET = 'iso-8859-1'
        self._handle_mail(self.multipart_msg_latin1)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        self.assertEqual(len(msg.files), 1)
        name = 'unnamed'
        content = '<html>' + c + '</html>\n'
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, name)
            self.assertEqual(f.content, content)
        self.assertEqual(msg.content, c)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: multipart/mixed; boundary="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
X-Roundup-Issue-Files: unnamed
X-Roundup-Issue-Id: 1


--utf-8
MIME-Version: 1.0
Content-Type: text/plain; charset="iso-8859-1"
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test.test> added the comment:

umlaut =E4=F6=FC=C4=D6=DC=DF

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
--utf-8
Content-Type: text/html
MIME-Version: 1.0
Content-Transfer-Encoding: base64
Content-Disposition: attachment;
 filename="unnamed"

PGh0bWw+dW1sYXV0IMOkw7bDvMOEw5bDnMOfPC9odG1sPgo=

--utf-8--
''')

    def testMultipartRFC822(self):
        self.doNewIssue()
        self._handle_mail(self.multipart_msg_rfc822)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        self.assertEqual(len(msg.files), 1)
        name = "Fwd: Original email subject.eml"
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, name)
        self.assertEqual(msg.content, 'First part: Text')
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: multipart/mixed; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
X-Roundup-Issue-Files: Fwd: Original email subject.eml
X-Roundup-Issue-Id: 1


--utf-8
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test.test> added the comment:

First part: Text

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
--utf-8
Content-Type: message/rfc822
MIME-Version: 1.0
Content-Disposition: attachment;
 filename="Fwd: Original email subject.eml"

Message-Id: <followup_dummy_id_2>
In-Reply-To: <dummy_test_message_id_2>
MIME-Version: 1.0
Subject: Fwd: Original email subject
Date: Mon, 23 Aug 2010 08:23:33 +0200
Content-Type: multipart/alternative; boundary="090500050101020406060002"

This is a multi-part message in MIME format.
--090500050101020406060002
Content-Type: text/plain; charset=ISO-8859-15; format=flowed
Content-Transfer-Encoding: 7bit

some text in inner email
========================

--090500050101020406060002
Content-Type: text/html; charset=ISO-8859-15
Content-Transfer-Encoding: 7bit

<html>
some text in inner email
========================
</html>

--090500050101020406060002--

--utf-8--
''')

    html_doc='''<html><body>
<script>
this must not be in output
</script>
<style>
p {display:block}
</style>
    <div class="header"><h1>Roundup</h1>
        <div id="searchbox" style="display: none">
          <form class="search" action="../search.html" method="get">
            <input type="text" name="q" size="18" />
            <input type="submit" value="Search" />
            <input type="hidden" name="check_keywords" value="yes" />
            <input type="hidden" name="area" value="default" />
          </form>
        </div>
        <script type="text/javascript">$('#searchbox').show(0);</script>
    </div>
       <ul class="current">
<li class="toctree-l1"><a class="reference internal" href="../index.html">Home</a></li>
<li class="toctree-l1"><a class="reference external" href="http://pypi.python.org/pypi/roundup">Download</a></li>
<li class="toctree-l1 current"><a class="reference internal" href="../docs.html">Docs</a><ul class="current">
<li class="toctree-l2"><a class="reference internal" href="features.html">Roundup Features</a></li>
<li class="toctree-l2 current"><a class="current reference internal" href="">Installing Roundup</a></li>
<li class="toctree-l2"><a class="reference internal" href="upgrading.html">Upgrading to newer versions of Roundup</a></li>
<li class="toctree-l2"><a class="reference internal" href="FAQ.html">Roundup FAQ</a></li>
<li class="toctree-l2"><a class="reference internal" href="user_guide.html">User Guide</a></li>
<li class="toctree-l2"><a class="reference internal" href="customizing.html">Customising Roundup</a></li>
<li class="toctree-l2"><a class="reference internal" href="admin_guide.html">Administration Guide</a></li>
</ul>
<div class="section" id="prerequisites">
<h2><a class="toc-backref" href="#id5">Prerequisites</a></h2>
<p>Roundup requires Python 2.5 or newer (but not Python 3) with a functioning
anydbm module. Download the latest version from <a class="reference external" href="http://www.python.org/">http://www.python.org/</a>.
It is highly recommended that users install the latest patch version
of python as these contain many fixes to serious bugs.</p>
<p>Some variants of Linux will need an additional &#8220;python dev&#8221; package
installed for Roundup installation to work. Debian and derivatives, are
known to require this.</p>
<p>If you&#8217;re on windows, you will either need to be using the ActiveState python
distribution (at <a class="reference external" href="http://www.activestate.com/Products/ActivePython/">http://www.activestate.com/Products/ActivePython/</a>), or you&#8217;ll
have to install the win32all package separately (get it from
<a class="reference external" href="http://starship.python.net/crew/mhammond/win32/">http://starship.python.net/crew/mhammond/win32/</a>).</p>
</div>
umlaut =E4=F6=FC=C4=D6=DC=DF</body>
</html>
'''
# FIXME append  =E4=F6=FC=C4=D6=DC=DF before </body>
#       to test quoted printable conversion

    multipart_msg_notext = '''From: mary <mary@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...
Content-Type: multipart/alternative; boundary=001485f339f8f361fb049188dbba


--001485f339f8f361fb049188dbba
Content-Type: text/csv; charset=ISO-8859-1
Content-Transfer-Encoding: quoted-printable

75,23,16,18

--001485f339f8f361fb049188dbba
Content-Type: text/html; charset=ISO-8859-1
Content-Transfer-Encoding: quoted-printable

%s
--001485f339f8f361fb049188dbba--
'''%html_doc

    def testMultipartTextifyHTML(self):
        text_fragments = ['Roundup\n        Home\nDownload\nDocs\nRoundup Features\nInstalling Roundup\nUpgrading to newer versions of Roundup\nRoundup FAQ\nUser Guide\nCustomising Roundup\nAdministration Guide\nPrerequisites\n\nRoundup requires Python 2.5 or newer (but not Python 3) with a functioning\nanydbm module. Download the latest version from http://www.python.org/.\nIt is highly recommended that users install the latest patch version\nof python as these contain many fixes to serious bugs.\n\nSome variants of Linux will need an additional ', ('python dev', u2s(u'\u201cpython dev\u201d')), ' package\ninstalled for Roundup installation to work. Debian and derivatives, are\nknown to require this.\n\nIf you', (u2s(u'\u2019'), ''), 're on windows, you will either need to be using the ActiveState python\ndistribution (at http://www.activestate.com/Products/ActivePython/), or you', (u2s(u'\u2019'), ''), 'll\nhave to install the win32all package separately (get it from\nhttp://starship.python.net/crew/mhammond/win32/).\n\numlaut']

#  \xc3\xa4\xc3\xb6\xc3\xbc\xc3\x84\xc3\x96\xc3\x9c\xc3\x9f
# append above with leading space to end of mycontent. It is the 
# translated content when =E4=F6=FC=C4=D6=DC=DF is added to the html
# input.
        self.doNewIssue()
        self.db.config.MAILGW_CONVERT_HTMLTOTEXT = 'dehtml'
        self._handle_mail(self.multipart_msg_notext)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode(messages[-1])
        # html converted to utf-8 text
        self.compareStringFragments(msg.content,
                                    text_fragments + [b2s(b" \xc3\xa4\xc3\xb6\xc3\xbc\xc3\x84\xc3\x96\xc3\x9c\xc3\x9f")])
        self.assertEqual(msg.type, None)
        self.assertEqual(len(msg.files), 2)
        name = "unnamed" # no name for any files
        types = { 0: "text/csv", 1: "text/html" }
        # replace quoted printable string at end of html document
        # with it's utf-8 encoded equivalent so comparison
        # works.
        content = { 0: "75,23,16,18\n",
                    1: self.html_doc.replace(" =E4=F6=FC=C4=D6=DC=DF",
                                             b2s(b" \xc3\xa4\xc3\xb6\xc3\xbc\xc3\x84\xc3\x96\xc3\x9c\xc3\x9f")) }
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, name)
            self.assertEqual(f.type, types[n])
            self.assertEqual(f.content, content[n])

            self.compareMessages(self._get_mail()
                                 .replace('=E2=80=99', '')
                                 .replace('=E2=80=9C', '')
                                 .replace('=E2=80=9D', '')
                                 .replace('==\n', '===\n\n').replace('=\n', ''),
'''From roundup-admin@your.tracker.email.domain.example Thu Oct 10 02:42:14 2017
FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: multipart/mixed; boundary="===============6077820410007357357=="
MIME-Version: 1.0
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-issue-status: chatting
X-Roundup-issue-files: unnamed, unnamed
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: "Contrary, Mary" <issue_tracker@your.tracker.email.domain.example>
Date: Thu, 12 Oct 2017 02:42:14 +0000
Precedence: bulk
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Version: 1.5.1
X-Roundup-Issue-Id: 1

--===============6077820410007357357==
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: quoted-printable


Contrary, Mary <mary@test.test> added the comment:

Roundup
        Home
Download
Docs
Roundup Features
Installing Roundup
Upgrading to newer versions of Roundup
Roundup FAQ
User Guide
Customising Roundup
Administration Guide
Prerequisites

Roundup requires Python 2.5 or newer (but not Python 3) with a functioning
anydbm module. Download the latest version from http://www.python.org/.
It is highly recommended that users install the latest patch version
of python as these contain many fixes to serious bugs.

Some variants of Linux will need an additional python dev package
installed for Roundup installation to work. Debian and derivatives, are
known to require this.

If youre on windows, you will either need to be using the ActiveState python
distribution (at http://www.activestate.com/Products/ActivePython/), or youll
have to install the win32all package separately (get it from
http://starship.python.net/crew/mhammond/win32/).

umlaut =C3=A4=C3=B6=C3=BC=C3=84=C3=96=C3=9C=C3=9F

----------
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
--===============6077820410007357357==
Content-Type: text/csv
MIME-Version: 1.0
Content-Transfer-Encoding: base64
Content-Disposition: attachment;
 filename="unnamed"

NzUsMjMsMTYsMTgK

--===============6077820410007357357==
Content-Type: text/html
MIME-Version: 1.0
Content-Transfer-Encoding: base64
Content-Disposition: attachment;
 filename="unnamed"

PGh0bWw+PGJvZHk+CjxzY3JpcHQ+CnRoaXMgbXVzdCBub3QgYmUgaW4gb3V0cHV0Cjwvc2NyaXB0
Pgo8c3R5bGU+CnAge2Rpc3BsYXk6YmxvY2t9Cjwvc3R5bGU+CiAgICA8ZGl2IGNsYXNzPSJoZWFk
ZXIiPjxoMT5Sb3VuZHVwPC9oMT4KICAgICAgICA8ZGl2IGlkPSJzZWFyY2hib3giIHN0eWxlPSJk
aXNwbGF5OiBub25lIj4KICAgICAgICAgIDxmb3JtIGNsYXNzPSJzZWFyY2giIGFjdGlvbj0iLi4v
c2VhcmNoLmh0bWwiIG1ldGhvZD0iZ2V0Ij4KICAgICAgICAgICAgPGlucHV0IHR5cGU9InRleHQi
IG5hbWU9InEiIHNpemU9IjE4IiAvPgogICAgICAgICAgICA8aW5wdXQgdHlwZT0ic3VibWl0IiB2
YWx1ZT0iU2VhcmNoIiAvPgogICAgICAgICAgICA8aW5wdXQgdHlwZT0iaGlkZGVuIiBuYW1lPSJj
aGVja19rZXl3b3JkcyIgdmFsdWU9InllcyIgLz4KICAgICAgICAgICAgPGlucHV0IHR5cGU9Imhp
ZGRlbiIgbmFtZT0iYXJlYSIgdmFsdWU9ImRlZmF1bHQiIC8+CiAgICAgICAgICA8L2Zvcm0+CiAg
ICAgICAgPC9kaXY+CiAgICAgICAgPHNjcmlwdCB0eXBlPSJ0ZXh0L2phdmFzY3JpcHQiPiQoJyNz
ZWFyY2hib3gnKS5zaG93KDApOzwvc2NyaXB0PgogICAgPC9kaXY+CiAgICAgICA8dWwgY2xhc3M9
ImN1cnJlbnQiPgo8bGkgY2xhc3M9InRvY3RyZWUtbDEiPjxhIGNsYXNzPSJyZWZlcmVuY2UgaW50
ZXJuYWwiIGhyZWY9Ii4uL2luZGV4Lmh0bWwiPkhvbWU8L2E+PC9saT4KPGxpIGNsYXNzPSJ0b2N0
cmVlLWwxIj48YSBjbGFzcz0icmVmZXJlbmNlIGV4dGVybmFsIiBocmVmPSJodHRwOi8vcHlwaS5w
eXRob24ub3JnL3B5cGkvcm91bmR1cCI+RG93bmxvYWQ8L2E+PC9saT4KPGxpIGNsYXNzPSJ0b2N0
cmVlLWwxIGN1cnJlbnQiPjxhIGNsYXNzPSJyZWZlcmVuY2UgaW50ZXJuYWwiIGhyZWY9Ii4uL2Rv
Y3MuaHRtbCI+RG9jczwvYT48dWwgY2xhc3M9ImN1cnJlbnQiPgo8bGkgY2xhc3M9InRvY3RyZWUt
bDIiPjxhIGNsYXNzPSJyZWZlcmVuY2UgaW50ZXJuYWwiIGhyZWY9ImZlYXR1cmVzLmh0bWwiPlJv
dW5kdXAgRmVhdHVyZXM8L2E+PC9saT4KPGxpIGNsYXNzPSJ0b2N0cmVlLWwyIGN1cnJlbnQiPjxh
IGNsYXNzPSJjdXJyZW50IHJlZmVyZW5jZSBpbnRlcm5hbCIgaHJlZj0iIj5JbnN0YWxsaW5nIFJv
dW5kdXA8L2E+PC9saT4KPGxpIGNsYXNzPSJ0b2N0cmVlLWwyIj48YSBjbGFzcz0icmVmZXJlbmNl
IGludGVybmFsIiBocmVmPSJ1cGdyYWRpbmcuaHRtbCI+VXBncmFkaW5nIHRvIG5ld2VyIHZlcnNp
b25zIG9mIFJvdW5kdXA8L2E+PC9saT4KPGxpIGNsYXNzPSJ0b2N0cmVlLWwyIj48YSBjbGFzcz0i
cmVmZXJlbmNlIGludGVybmFsIiBocmVmPSJGQVEuaHRtbCI+Um91bmR1cCBGQVE8L2E+PC9saT4K
PGxpIGNsYXNzPSJ0b2N0cmVlLWwyIj48YSBjbGFzcz0icmVmZXJlbmNlIGludGVybmFsIiBocmVm
PSJ1c2VyX2d1aWRlLmh0bWwiPlVzZXIgR3VpZGU8L2E+PC9saT4KPGxpIGNsYXNzPSJ0b2N0cmVl
LWwyIj48YSBjbGFzcz0icmVmZXJlbmNlIGludGVybmFsIiBocmVmPSJjdXN0b21pemluZy5odG1s
Ij5DdXN0b21pc2luZyBSb3VuZHVwPC9hPjwvbGk+CjxsaSBjbGFzcz0idG9jdHJlZS1sMiI+PGEg
Y2xhc3M9InJlZmVyZW5jZSBpbnRlcm5hbCIgaHJlZj0iYWRtaW5fZ3VpZGUuaHRtbCI+QWRtaW5p
c3RyYXRpb24gR3VpZGU8L2E+PC9saT4KPC91bD4KPGRpdiBjbGFzcz0ic2VjdGlvbiIgaWQ9InBy
ZXJlcXVpc2l0ZXMiPgo8aDI+PGEgY2xhc3M9InRvYy1iYWNrcmVmIiBocmVmPSIjaWQ1Ij5QcmVy
ZXF1aXNpdGVzPC9hPjwvaDI+CjxwPlJvdW5kdXAgcmVxdWlyZXMgUHl0aG9uIDIuNSBvciBuZXdl
ciAoYnV0IG5vdCBQeXRob24gMykgd2l0aCBhIGZ1bmN0aW9uaW5nCmFueWRibSBtb2R1bGUuIERv
d25sb2FkIHRoZSBsYXRlc3QgdmVyc2lvbiBmcm9tIDxhIGNsYXNzPSJyZWZlcmVuY2UgZXh0ZXJu
YWwiIGhyZWY9Imh0dHA6Ly93d3cucHl0aG9uLm9yZy8iPmh0dHA6Ly93d3cucHl0aG9uLm9yZy88
L2E+LgpJdCBpcyBoaWdobHkgcmVjb21tZW5kZWQgdGhhdCB1c2VycyBpbnN0YWxsIHRoZSBsYXRl
c3QgcGF0Y2ggdmVyc2lvbgpvZiBweXRob24gYXMgdGhlc2UgY29udGFpbiBtYW55IGZpeGVzIHRv
IHNlcmlvdXMgYnVncy48L3A+CjxwPlNvbWUgdmFyaWFudHMgb2YgTGludXggd2lsbCBuZWVkIGFu
IGFkZGl0aW9uYWwgJiM4MjIwO3B5dGhvbiBkZXYmIzgyMjE7IHBhY2thZ2UKaW5zdGFsbGVkIGZv
ciBSb3VuZHVwIGluc3RhbGxhdGlvbiB0byB3b3JrLiBEZWJpYW4gYW5kIGRlcml2YXRpdmVzLCBh
cmUKa25vd24gdG8gcmVxdWlyZSB0aGlzLjwvcD4KPHA+SWYgeW91JiM4MjE3O3JlIG9uIHdpbmRv
d3MsIHlvdSB3aWxsIGVpdGhlciBuZWVkIHRvIGJlIHVzaW5nIHRoZSBBY3RpdmVTdGF0ZSBweXRo
b24KZGlzdHJpYnV0aW9uIChhdCA8YSBjbGFzcz0icmVmZXJlbmNlIGV4dGVybmFsIiBocmVmPSJo
dHRwOi8vd3d3LmFjdGl2ZXN0YXRlLmNvbS9Qcm9kdWN0cy9BY3RpdmVQeXRob24vIj5odHRwOi8v
d3d3LmFjdGl2ZXN0YXRlLmNvbS9Qcm9kdWN0cy9BY3RpdmVQeXRob24vPC9hPiksIG9yIHlvdSYj
ODIxNztsbApoYXZlIHRvIGluc3RhbGwgdGhlIHdpbjMyYWxsIHBhY2thZ2Ugc2VwYXJhdGVseSAo
Z2V0IGl0IGZyb20KPGEgY2xhc3M9InJlZmVyZW5jZSBleHRlcm5hbCIgaHJlZj0iaHR0cDovL3N0
YXJzaGlwLnB5dGhvbi5uZXQvY3Jldy9taGFtbW9uZC93aW4zMi8iPmh0dHA6Ly9zdGFyc2hpcC5w
eXRob24ubmV0L2NyZXcvbWhhbW1vbmQvd2luMzIvPC9hPikuPC9wPgo8L2Rpdj4KdW1sYXV0IMOk
w7bDvMOEw5bDnMOfPC9ib2R5Pgo8L2h0bWw+Cg==

--===============6077820410007357357==--
''')


    def testMultipartRFC822Unpack(self):
        self.doNewIssue()
        self.db.config.MAILGW_UNPACK_RFC822 = True
        self._handle_mail(self.multipart_msg_rfc822)
        messages = self.db.issue.get('1', 'messages')
        messages.sort()
        msg = self.db.msg.getnode (messages[-1])
        self.assertEqual(len(msg.files), 2)
        t = 'some text in inner email\n========================\n'
        content = {0 : t, 1 : '<html>\n' + t + '</html>\n'}
        for n, id in enumerate (msg.files):
            f = self.db.file.getnode (id)
            self.assertEqual(f.name, 'unnamed')
            if n in content :
                self.assertEqual(f.content, content [n])
        self.assertEqual(msg.content, 'First part: Text')

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
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable
X-Roundup-Issue-Id: 1


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
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable
X-Roundup-Issue-Id: 1


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

    def testFollowupUTF8(self):
        self.doNewIssue()

        self._handle_mail('''Content-Type: text/plain;
  charset="utf-8"
Content-Transfer-Encoding: quoted-printable
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing... [assignedto=mary; nosy=+john]

This is a followup with UTF-8 characters in it:
=C3=A4=C3=B6=C3=BC=C3=84=C3=96=C3=9C=C3=9F
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
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable
X-Roundup-Issue-Id: 1


richard <richard@test.test> added the comment:

This is a followup with UTF-8 characters in it:
=C3=A4=C3=B6=C3=BC=C3=84=C3=96=C3=9C=C3=9F

----------
assignedto:  -> mary
nosy: +john, mary
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testFollowupNoSubjectChange(self):
        self.db.config.MAILGW_SUBJECT_UPDATES_TITLE = 'no'
        self.doNewIssue()

        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Wrzlbrmft... [assignedto=mary; nosy=+john]

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
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable
X-Roundup-Issue-Id: 1

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
        self.assertEqual(self.db.issue.get('1','title'), 'Testing...')

    def testFollowupExplicitSubjectChange(self):
        self.doNewIssue()

        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Wrzlbrmft... [assignedto=mary; nosy=+john; title=new title]

This is a followup
''')
        l = self.db.issue.get('1', 'nosy')
        l.sort()
        self.assertEqual(l, [self.chef_id, self.richard_id, self.mary_id,
            self.john_id])

        # check that the message has the right tx_Source
        l = self.db.msg.get('2', 'tx_Source')
        self.assertEqual(l, 'email')

        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test.test, mary@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] new title
To: chef@bork.bork.bork, john@test.test, mary@test.test
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable
X-Roundup-Issue-Id: 1

richard <richard@test.test> added the comment:

This is a followup

----------
assignedto:  -> mary
nosy: +john, mary
status: unread -> chatting
title: Testing... -> new title

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testNosyGeneration(self):
        self.db.tx_Source = "email"
        self.db.issue.create(title='test')

        # create a nosy message
        msg = self.db.msg.create(content='This is a test',
            author=self.richard_id, messageid='<dummy_test_message_id>')
        self.db.journaltag = 'richard'
        l = self.db.issue.create(title='test', messages=[msg],
            nosy=[self.chef_id, self.mary_id, self.john_id])


        # check that message has right tx_Source
        self.assertEqual(self.db.msg.get('1', 'tx_Source'), 'email')

        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test.test, mary@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue2] test
To: chef@bork.bork.bork, john@test.test, mary@test.test
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
Content-Transfer-Encoding: quoted-printable
X-Roundup-Issue-Id: 2


New submission from richard <richard@test.test>:

This is a test

----------
messages: 1
nosy: Chef, john, mary, richard
status: unread
title: test
tx_Source: email

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue2>
_______________________________________________________________________
''')

    def testNosyMessageCcBccEtc(self):
        self.doNewIssue()
        oldvalues = self.db.getnode('issue', '1').copy()
        oldvalues['assignedto'] = None
        # reconstruct old behaviour: This would reuse the
        # database-handle from the doNewIssue above which has committed
        # as user "Chef". So we close and reopen the db as that user.
        #self.db.close() actually don't close 'cos this empties memorydb
        self.db = self.instance.open('Chef')
        self.db.issue.set('1', assignedto=self.chef_id)
        self.db.commit()
        # note user 3 is both in cc and bcc. The one in cc takes
        # precedence and stops the bcc copy from being sent to user 3..
        # new email is generated for bcc peoples: admin and kermit
        # get it.
        self.db.issue.nosymessage('1', None, oldvalues,
                                  cc=['3','4', '5'], bcc=['1', '3', '5'],
                                  cc_emails=['john@example.com'],
                                  bcc_emails=["kermit@example.com"])
        new_mail = ""
        for line in self._get_mail().split("\n"):
            if "Message-Id: " in line:
                continue
            if "Date: " in line:
                continue
            new_mail += line+"\n"

        # new_mail is a mbox style string with 2 emails.
        # we need to split the emails and compare.
        new_mails=new_mail.split("\nFrom ")
        # restore the "From " prefix removed from first line of
        # second message by strip.
        new_mails[1]="From " + new_mail.split("\nFrom ")[1]

        self.compareMessages(new_mails[0], """
FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, fred@example.com, john@example.com, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, fred@example.com, john@example.com, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
X-Roundup-Version: 1.3.3
X-Roundup-Issue-Id: 1
In-Reply-To: <dummy_test_message_id>
MIME-Version: 1.0
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
Content-Transfer-Encoding: quoted-printable


Change by Bork, Chef <chef@bork.bork.bork>:


----------
assignedto:  -> Chef

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
""")

        self.compareMessages(new_mails[1], """
FROM: roundup-admin@your.tracker.email.domain.example
TO: admin@test.com, kermit@example.com
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, fred@example.com, john@example.com, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
X-Roundup-Version: 1.3.3
X-Roundup-Issue-Id: 1
In-Reply-To: <dummy_test_message_id>
MIME-Version: 1.0
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
Content-Transfer-Encoding: quoted-printable


Change by Bork, Chef <chef@bork.bork.bork>:


----------
assignedto:  -> Chef

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
""")


    def testNosyMessageNoteFilter(self):
        def note_filter(original_note, issue_id, db, newvalues, oldvalues):
            return 'This content came from note_filter().'
        self.doNewIssue()
        oldvalues = self.db.getnode('issue', '1').copy()
        oldvalues['assignedto'] = None
        # reconstruct old behaviour: This would reuse the
        # database-handle from the doNewIssue above which has committed
        # as user "Chef". So we close and reopen the db as that user.
        #self.db.close() actually don't close 'cos this empties memorydb
        self.db = self.instance.open('Chef')
        self.db.issue.set('1', assignedto=self.chef_id)
        self.db.commit()
        self.db.issue.nosymessage('1', None, oldvalues,
                                  cc=['3','4', '5'],
                                  cc_emails=['john@example.com'],
                                  note_filter=note_filter)
        new_mail = ""
        # Message-Id: and Date: change every time - remove them.
        for line in self._get_mail().split("\n"):
            if "Message-Id: " in line:
                continue
            if "Date: " in line:
                continue
            new_mail += line+"\n"

        self.compareMessages(new_mail, """
FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, fred@example.com, john@example.com, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, fred@example.com, john@example.com, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
X-Roundup-Version: 1.3.3
X-Roundup-Issue-Id: 1
In-Reply-To: <dummy_test_message_id>
MIME-Version: 1.0
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
Content-Transfer-Encoding: quoted-printable


Change by Bork, Chef <chef@bork.bork.bork>:

This content came from note_filter().

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
""")


    def testPropertyChangeOnly(self):
        self.doNewIssue()
        oldvalues = self.db.getnode('issue', '1').copy()
        oldvalues['assignedto'] = None
        # reconstruct old behaviour: This would reuse the
        # database-handle from the doNewIssue above which has committed
        # as user "Chef". So we close and reopen the db as that user.
        #self.db.close() actually don't close 'cos this empties memorydb
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
X-Roundup-Issue-Id: 1
In-Reply-To: <dummy_test_message_id>
MIME-Version: 1.0
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
Content-Transfer-Encoding: quoted-printable


Change by Bork, Chef <chef@bork.bork.bork>:


----------
assignedto:  -> Chef

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
""")


    def testNosyMessageSettingSubject(self):
        self.doNewIssue()
        oldvalues = self.db.getnode('issue', '1').copy()
        oldvalues['assignedto'] = None
        # reconstruct old behaviour: This would reuse the
        # database-handle from the doNewIssue above which has committed
        # as user "Chef". So we close and reopen the db as that user.
        #self.db.close() actually don't close 'cos this empties memorydb
        self.db = self.instance.open('Chef')
        self.db.issue.set('1', assignedto=self.chef_id)
        self.db.commit()
        self.db.issue.nosymessage('1', None, oldvalues, subject="test")

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
Subject: test
To: chef@bork.bork.bork, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Status: unread
X-Roundup-Version: 1.3.3
X-Roundup-Issue-Id: 1
In-Reply-To: <dummy_test_message_id>
MIME-Version: 1.0
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
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

        l = self.db.msg.get('2', 'tx_Source')
        self.assertEqual(l, 'email')

        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test.test, mary@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, john@test.test, mary@test.test
From: richard <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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

    simple_followup = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: john@test.test
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] Testing...

This is a followup
'''

    def testFollowupNosyAuthor(self):
        self.doNewIssue()
        self.db.config.ADD_AUTHOR_TO_NOSY = 'yes'
        self._handle_mail(self.simple_followup)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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
        self._handle_mail(self.simple_followup)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, john@test.test, richard@test.test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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

    def testFollowupNosyAuthorNosyCopy(self):
        self.doNewIssue()
        self.db.config.ADD_AUTHOR_TO_NOSY = 'yes'
        self.db.config.MESSAGES_TO_AUTHOR = 'nosy'
        self._handle_mail(self.simple_followup)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, john@test.test, richard@test.test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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
        self._handle_mail(self.simple_followup)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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

    def testFollowupNoNosyAuthorNoCopy(self):
        self.doNewIssue()
        self.instance.config.ADD_AUTHOR_TO_NOSY = 'no'
        self.instance.config.MESSAGES_TO_AUTHOR = 'nosy'
        self._handle_mail(self.simple_followup)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, richard@test.test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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

    # this is a pathological case where the author is *not* on the nosy
    # list but gets the message; test documents existing behaviour
    def testFollowupNoNosyAuthorButCopy(self):
        self.doNewIssue()
        self.instance.config.ADD_AUTHOR_TO_NOSY = 'no'
        self.instance.config.MESSAGES_TO_AUTHOR = 'yes'
        self._handle_mail(self.simple_followup)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: chef@bork.bork.bork, john@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: chef@bork.bork.bork, john@test.test, richard@test.test
From: John Doe <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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

    def testNosyReplytoTracker(self):
        self.db.config.TRACKER_REPLYTO_ADDRESS = ''
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
TO: mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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
tx_Source: email

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testNosyReplytoSomeaddress(self):
        self.db.config.TRACKER_REPLYTO_ADDRESS = 'replyto@me.example.com'
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
TO: mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: replyto@me.example.com
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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
tx_Source: email

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testNosyReplytoAuthor(self):
        self.db.config.TRACKER_REPLYTO_ADDRESS = 'AUTHOR'
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
TO: mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: "Bork, Chef" <chef@bork.bork.bork>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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
tx_Source: email

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testNewUserAuthor(self):
        self.db.commit()
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
        self.db.security.role['anonymous'].permissions=[]
        anonid = self.db.user.lookup('anonymous')
        self.db.user.set(anonid, roles='Anonymous')
        try:
            self._handle_mail(message)
        except Unauthorized as value:
            body_diff = self.assertEqual(str(value), """
You are not a registered user.

Unknown address: fubar@bork.bork.bork
""")
            assert not body_diff, body_diff
        else:
            raise AssertionError("Unauthorized not raised when handling mail")

        # Add Web Access role to anonymous, and try again to make sure
        # we get a "please register at:" message this time.
        p = [
            self.db.security.getPermission('Register', 'user'),
            self.db.security.getPermission('Web Access', None),
        ]
        self.db.security.role['anonymous'].permissions=p
        try:
            self._handle_mail(message)
        except Unauthorized as value:
            body_diff = self.assertEqual(str(value), """
You are not a registered user. Please register at:

http://tracker.example/cgi-bin/roundup.cgi/bugs/user?@template=register

...before sending mail to the tracker.

Unknown address: fubar@bork.bork.bork
""")
            assert not body_diff, body_diff
        else:
            raise AssertionError("Unauthorized not raised when handling mail")

        # Make sure list of users is the same as before.
        m = self.db.user.list()
        m.sort()
        self.assertEqual(l, m)

        # now with the permission
        p = [
            self.db.security.getPermission('Register', 'user'),
            self.db.security.getPermission('Email Access', None),
        ]
        self.db.security.role['anonymous'].permissions=p
        self._handle_mail(message)
        m = self.db.user.list()
        m.sort()
        self.assertNotEqual(l, m)

    def testNewUserAuthorEncodedName(self):
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
        self._allowAnonymousSubmit()
        self._handle_mail(message)
        m = set(self.db.user.list())
        new = list(m - l)[0]
        name = self.db.user.get(new, 'realname')
        self.assertEqual(name, 'H€llo')

    def testNewUserAuthorMixedEncodedName(self):
        l = set(self.db.user.list())
        # From: name has Euro symbol in it
        message = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Firstname =?utf-8?b?w6TDtsOf?= Last <fubar@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Test =?utf-8?b?w4TDlsOc?= umlauts
 X1
 X2

This is a test submission of a new issue.
'''
        self._allowAnonymousSubmit()
        self._handle_mail(message)
        title = self.db.issue.get('1', 'title')
        self.assertEqual(title, b2s(b'Test \xc3\x84\xc3\x96\xc3\x9c umlauts X1 X2'))
        m = set(self.db.user.list())
        new = list(m - l)[0]
        name = self.db.user.get(new, 'realname')
        self.assertEqual(name, b2s(b'Firstname \xc3\xa4\xc3\xb6\xc3\x9f Last'))

    def testNewUserAuthorMixedEncodedNameSpacing(self):
        l = set(self.db.user.list())
        # From: name has Euro symbol in it
        message = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: (=?utf-8?b?w6TDtsOf?==?utf-8?b?w6TDtsOf?=) <fubar@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Test (=?utf-8?b?w4TDlsOc?=) umlauts
 X1

This is a test submission of a new issue.
'''
        self._allowAnonymousSubmit()
        self._handle_mail(message)
        title = self.db.issue.get('1', 'title')
        self.assertEqual(title, b2s(b'Test (\xc3\x84\xc3\x96\xc3\x9c) umlauts X1'))
        m = set(self.db.user.list())
        new = list(m - l)[0]
        name = self.db.user.get(new, 'realname')
        self.assertEqual(name,
            b2s(b'(\xc3\xa4\xc3\xb6\xc3\x9f\xc3\xa4\xc3\xb6\xc3\x9f)'))

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
        # trap_exc=1: we want a bounce message:
        ret = self._handle_mail(message, trap_exc=1)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
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

--===============0639262320==
Content-Type: text/plain; charset="us-ascii"
MIME-Version: 1.0
Content-Transfer-Encoding: 7bit



You are not a registered user. Please register at:

http://tracker.example/cgi-bin/roundup.cgi/bugs/user?@template=register

...before sending mail to the tracker.

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
        self.db.user.set(self.mary_id,
            realname=u2s(u'\xe4\xf6\xfc\xc4\xd6\xdc\xdf, Mary'))
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
From: =?utf-8?b?w6TDtsO8w4TDlsOcw58sIE1hcnk=?=
 <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


=C3=A4=C3=B6=C3=BC=C3=84=C3=96=C3=9C=C3=9F, Mary <mary@test.test> added the=
 comment:

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
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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
        self._handle_mail('''From: mary <mary@test.test>
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
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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
        self._handle_mail('''From: mary <mary@test.test>
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
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
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

    firstquotingtest = '''Content-Type: text/plain;
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
'''

    def testEmailQuoting(self):
        self.instance.config.EMAIL_KEEP_QUOTED_TEXT = 'no'
        # FIXME possible bug. Messages retreived from content are missing
        # trailing newlines. Probably due to signature stripping.
        # so nuke all trailing newlines.
        self.innerTestQuoting(self.firstquotingtest, '''This is a followup''', 'This is a followup')

    def testEmailQuotingNewIsNew(self):
        self.instance.config.EMAIL_KEEP_QUOTED_TEXT = 'new'
        # create the message, remove the prefix from subject
        testmessage=self.firstquotingtest.replace(" Re: [issue1]", "")
        nodeid = self._handle_mail(testmessage)

        msgs = self.db.issue.get(nodeid, 'messages')
        # validate content and summary
        content = self.db.msg.get(msgs[0], 'content')
        self.assertEqual(content, '''Blah blah wrote:
> Blah bklaskdfj sdf asdf jlaskdf skj sdkfjl asdf
>  skdjlkjsdfalsdkfjasdlfkj dlfksdfalksd fj
>

This is a followup''')

        summary = self.db.msg.get(msgs[0], 'summary')
        self.assertEqual(summary,  '''This is a followup''')

    def testEmailQuotingNewIsFollowup(self):
        self.instance.config.EMAIL_KEEP_QUOTED_TEXT = 'new'
        # create issue1 that we can followup on
        self.doNewIssue()
        # add the second message to the issue
        nodeid = self._handle_mail(self.firstquotingtest)
        msgs = self.db.issue.get(nodeid, 'messages')
        # check second message for accuracy
        content = self.db.msg.get(msgs[1], 'content')
        summary = self.db.msg.get(msgs[1], 'summary')
        self.assertEqual(content,  '''This is a followup''')
        self.assertEqual(summary,  '''This is a followup''')

    def testEmailBodyUnchangedNewIsYes(self):
        mysig = "--\nmy sig\n\n"
        self.instance.config.EMAIL_LEAVE_BODY_UNCHANGED = 'yes'
        # create the message, remove the prefix from subject
        testmessage=self.firstquotingtest.replace(" Re: [issue1]", "") + mysig
        nodeid = self._handle_mail(testmessage)

        msgs = self.db.issue.get(nodeid, 'messages')
        # validate content and summary
        content = self.db.msg.get(msgs[0], 'content')
        self.assertEqual(content, '''Blah blah wrote:
> Blah bklaskdfj sdf asdf jlaskdf skj sdkfjl asdf
>  skdjlkjsdfalsdkfjasdlfkj dlfksdfalksd fj
>

This is a followup\n''' + mysig[:-2])
        # the :-2 requrement to strip the trailing newlines is probably a bug
        # somewhere mailgw has right content maybe trailing \n are stripped by
        # msg or something.

        summary = self.db.msg.get(msgs[0], 'summary')
        self.assertEqual(summary,  '''This is a followup''')

    def testEmailBodyUnchangedFollowupIsYes(self):
        mysig = "--\nmy sig\n\n"
        self.instance.config.EMAIL_LEAVE_BODY_UNCHANGED = 'yes'

        # create issue1 that we can followup on
        self.doNewIssue()
        testmessage=self.firstquotingtest + mysig
        nodeid = self._handle_mail(testmessage)
        msgs = self.db.issue.get(nodeid, 'messages')
        # validate content and summary
        content = self.db.msg.get(msgs[1], 'content')
        self.assertEqual(content, '''Blah blah wrote:
> Blah bklaskdfj sdf asdf jlaskdf skj sdkfjl asdf
>  skdjlkjsdfalsdkfjasdlfkj dlfksdfalksd fj
>

This is a followup\n''' + mysig[:-2])
        # the :-2 requrement to strip the trailing newlines is probably a bug
        # somewhere mailgw has right content maybe trailing \n are stripped by
        # msg or something.

        summary = self.db.msg.get(msgs[1], 'summary')
        self.assertEqual(summary,  '''This is a followup''')

    def testEmailReplaceBodyNewIsNew(self):
        mysig = "--\nmy sig\n\n"
        self.instance.config.EMAIL_LEAVE_BODY_UNCHANGED = 'new'
        # create the message, remove the prefix from subject
        testmessage=self.firstquotingtest.replace(" Re: [issue1]", "") + mysig
        nodeid = self._handle_mail(testmessage)

        msgs = self.db.issue.get(nodeid, 'messages')
        # validate content and summary
        content = self.db.msg.get(msgs[0], 'content')
        self.assertEqual(content, '''Blah blah wrote:
> Blah bklaskdfj sdf asdf jlaskdf skj sdkfjl asdf
>  skdjlkjsdfalsdkfjasdlfkj dlfksdfalksd fj
>

This is a followup\n''' + mysig[:-2])
        # the :-2 requrement to strip the trailing newlines is probably a bug
        # somewhere mailgw has right content maybe trailing \n are stripped by
        # msg or something.

        summary = self.db.msg.get(msgs[0], 'summary')
        self.assertEqual(summary,  '''This is a followup''')

    def testEmailReplaceBodyNewIsFollowup(self):
        mysig = "\n--\nmy sig\n"
        self.instance.config.EMAIL_LEAVE_BODY_UNCHANGED = 'new'
        # create issue1 that we can followup on
        self.doNewIssue()
        # add the second message to the issue
        nodeid = self._handle_mail(self.firstquotingtest + mysig)
        msgs = self.db.issue.get(nodeid, 'messages')
        # check second message for accuracy
        content = self.db.msg.get(msgs[1], 'content')
        summary = self.db.msg.get(msgs[1], 'summary')
        self.assertEqual(content,  '''Blah blah wrote:\n> Blah bklaskdfj sdf asdf jlaskdf skj sdkfjl asdf\n>  skdjlkjsdfalsdkfjasdlfkj dlfksdfalksd fj\n>\n\nThis is a followup''')
        self.assertEqual(summary,  '''This is a followup''')

    def testEmailQuotingRemove(self):
        self.instance.config.EMAIL_KEEP_QUOTED_TEXT = 'yes'
        # FIXME possible bug. Messages retreived from content are missing
        # trailing newlines. Probably due to signature stripping.
        # so nuke all trailing newlines.
        self.innerTestQuoting(self.firstquotingtest, '''Blah blah wrote:
> Blah bklaskdfj sdf asdf jlaskdf skj sdkfjl asdf
>  skdjlkjsdfalsdkfjasdlfkj dlfksdfalksd fj
>

This is a followup''', 'This is a followup')

    secondquotingtest = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: Re: [issue1] Testing...

On Tue, Feb 23, 2010 at 8:46 AM, Someone <report@bugs.python.org> wrote:
> aa
> aa

AA:

 AA

AA

 AA

TEXT BEFORE QUOTE
> bb
> bb
>

BB
BB
BB
BB

> cc
>
> cc
>
>
> cc
>
> cc
>
> cc
>
CC

--
added signature
'''
    def testEmailQuoting2(self):
        self.instance.config.EMAIL_KEEP_QUOTED_TEXT = 'no'
        # FIXME possible bug. Messages retreived from content are missing
        # trailing newlines. Probably due to signature stripping.
        # so nuke all trailing newlines.
        self.innerTestQuoting(self.secondquotingtest, '''AA:

 AA

AA

 AA

TEXT BEFORE QUOTE

BB
BB
BB
BB

CC''', 'AA:')

    def testEmailQuotingRemove2(self):
        self.instance.config.EMAIL_KEEP_QUOTED_TEXT = 'yes'
        # FIXME possible bug. Messages retreived from content are missing
        # trailing newlines. Probably due to signature stripping.
        # so nuke all trailing newlines. That's what the trailing
        # [:-1] is doing on the '\n'.join(....)[8:-3]
        self.innerTestQuoting(self.secondquotingtest,
            '\n'.join(self.secondquotingtest.split('\n')[8:-3][:-1]), 'AA:')

    thirdquotingtest = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: Re: [issue1] Testing...

On Mon, Jan 02, 2012 at 06:14:27PM +0000, Someone wrote:
>
> aa
>
> aa
> aa
> aa
AA0
AA

> bb
> bb
> bb
BB

> cc
> cc
> cc
> cc
> cc
> cc

CC
CC
CC

CC
CC

CC
CC
CC
CC

CC

NAME
--
sig
sig
sig
sig
'''

    # This fails because the sig isn't removed (we currently remove the
    # sig only if the delimiter is the first line in a section)
    @expectedFailure
    def testEmailQuotingRemove3(self):
        self.instance.config.EMAIL_KEEP_QUOTED_TEXT = 'yes'
        self.innerTestQuoting(self.thirdquotingtest,
            '\n'.join(self.thirdquotingtest.split('\n')[8:-6]), 'AA0')

    def innerTestQuoting(self, msgtext, expect, summary=None):
        nodeid = self.doNewIssue()

        messages = self.db.issue.get(nodeid, 'messages')

        self._handle_mail(msgtext)
        # figure the new message id
        newmessages = self.db.issue.get(nodeid, 'messages')
        for msg in messages:
            newmessages.remove(msg)
        messageid = newmessages[0]

        self.assertEqual(self.db.msg.get(messageid, 'content'), expect)
        if summary:
            self.assertEqual (summary, self.db.msg.get(messageid, 'summary'))

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

    def testUserAlternateSubstringNomatch(self):
        i = self.db.user.create(username='user1', address='user1@foo.com',
                                alternate_addresses='x-user1@bar.com')
        self.assertEqual(uidFromAddress(self.db, ('', 'user1@bar.com'), 0), 0)
        self.assertEqual(uidFromAddress(self.db, ('', 'USER1@bar.com'), 0), 0)

    def testUserCreate(self):
        i = uidFromAddress(self.db, ('', 'user@foo.com'), 1)
        self.assertNotEqual(uidFromAddress(self.db, ('', 'user@bar.com'), 1), i)

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

    def testResentFromSwitchedOff(self):
        self.instance.config.EMAIL_KEEP_REAL_FROM = 'yes'
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
        self.assertEqual(l, [self.chef_id, self.richard_id])
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

    def testItsAutoSubmittedStupid(self):
        self.assertRaises(IgnoreBulk, self._handle_mail,
            '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
Auto-Submitted: Auto-Generated
To: issue_tracker@your.tracker.email.domain.example
Cc: richard@test.test
Message-Id: <dummy_test_message_id>
Subject: Re: [issue] Testing...

Hi, I'm on holidays, and this is a dumb auto-responder.
''')

    def testItsHumanSubmitted(self):
        ''' keep trailing spaces on Auto-submitted header
        '''
        self.db.keyword.create(name='Foo')
        self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: richard <richard@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Auto-submitted:   No  
Subject: [keyword1] Testing... [name=Bar]

''')
        self.assertEqual(self.db.keyword.get('1', 'name'), 'Bar')


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

    def testInvalidClassLooseReplyQuoted(self):
        self.instance.config.MAILGW_SUBJECT_PREFIX_PARSING = 'loose'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: Re: "[frobulated] testing"
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

Dumb mailers may put quotes around the subject after the reply prefix,
e.g. Re: "[issue1] bla bla"
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

    def testDoublePrefixLoose(self):
        self.instance.config.MAILGW_SUBJECT_PREFIX_PARSING = 'loose'
        self.instance.config.MAILGW_SUBJECT_SUFFIX_PARSING = 'loose'
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: [frobulated] [frobulatedagain] testing stuff after double prefix
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

''')
        assert not os.path.exists(SENDMAILDEBUG)
        self.assertEqual(self.db.issue.get(nodeid, 'title'),
            '[frobulated] [frobulatedagain] testing stuff after double prefix')

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

    def testOneCharSubject(self):
        message = '''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Subject: b
Cc: richard@test.test
Reply-To: chef@bork.bork.bork
Message-Id: <dummy_test_message_id>

'''
        try:
            self._handle_mail(message)
        except MailUsageError:
            self.fail('MailUsageError raised')

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

    def testSecurityMessagePermissionContent(self):
        id = self.doNewIssue()
        issue = self.db.issue.getnode (id)
        self.db.security.addRole(name='Nomsg')
        self.db.security.addPermissionToRole('Nomsg', 'Email Access')
        for cl in 'issue', 'file', 'keyword':
            for p in 'View', 'Edit', 'Create':
                self.db.security.addPermissionToRole('Nomsg', p, cl)
        self.db.user.set(self.mary_id, roles='Nomsg')
        nodeid = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: Chef <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id_2>
Subject: [issue%(id)s] Testing... [nosy=+mary]

Just a test reply
'''%locals())
        assert os.path.exists(SENDMAILDEBUG)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] Testing...
To: richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <dummy_test_message_id_2>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable


Bork, Chef <chef@bork.bork.bork> added the comment:

Just a test reply

----------
nosy: +mary
status: unread -> chatting

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testSpacesAroundMultilinkPropertyValue(self):
        self.db.keyword.create(name='Foo')
        self.db.keyword.create(name='Bar')
        self.db.keyword.create(name='Baz This')
        nodeid1 = self.doNewIssue()
        nodeid2 = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: "Bork, Chef" <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] set keyword [ keyword =+ Foo,Baz This ; nosy =+ mary ]

Set the Foo and Baz This keywords along with mary for nosy.
''')
        assert os.path.exists(SENDMAILDEBUG)
        self.compareMessages(self._get_mail(),
'''FROM: roundup-admin@your.tracker.email.domain.example
TO: mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] set keyword
To: mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
X-Roundup-Issue-Status: chatting
X-Roundup-Issue-keyword: Foo, Baz This
Content-Transfer-Encoding: quoted-printable

Bork, Chef <chef@bork.bork.bork> added the comment:

Set the Foo and Baz This keywords along with mary for nosy.

----------
keyword: +Baz This, Foo
nosy: +mary
status: unread -> chatting
title: Testing... -> set keyword

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
''')

    def testmsgHeaderPropertyAssignedto(self):
        ''' Test that setting the msg_header_property to an empty string
        suppresses the X-Roundup-issue-prop header in generated email.
        '''
        reference_email = '''FROM: roundup-admin@your.tracker.email.domain.example
TO: mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] set assignedto
To: mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
X-Roundup-Issue-Status: chatting
X-Roundup-Issue-Assignedto: mary
Content-Transfer-Encoding: quoted-printable

Bork, Chef <chef@bork.bork.bork> added the comment:

Check that assignedto makes it into an X-Header

----------
assignedto:  -> mary
nosy: +mary
status: unread -> chatting
title: Testing... -> set assignedto

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
'''        
        self.db.issue.properties['assignedto'].msg_header_property='username'

        nodeid1 = self.doNewIssue()
        nodeid2 = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: "Bork, Chef" <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] set assignedto [assignedto=mary]

Check that assignedto makes it into an X-Header
''')
        assert os.path.exists(SENDMAILDEBUG)
        self.compareMessages(self._get_mail(), reference_email)

    def testmsgHeaderPropertyEmptyString(self):
        ''' Test that setting the msg_header_property to an empty string
        suppresses the X-Roundup-issue-prop header in generated email.
        '''
        reference_email = '''FROM: roundup-admin@your.tracker.email.domain.example
TO: mary@test.test, richard@test.test
Content-Type: text/plain; charset="utf-8"
Subject: [issue1] set keyword
To: mary@test.test, richard@test.test
From: "Bork, Chef" <issue_tracker@your.tracker.email.domain.example>
Reply-To: Roundup issue tracker
 <issue_tracker@your.tracker.email.domain.example>
MIME-Version: 1.0
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
X-Roundup-Issue-Id: 1
X-Roundup-Issue-Status: chatting
Content-Transfer-Encoding: quoted-printable

Bork, Chef <chef@bork.bork.bork> added the comment:

Set the Foo and Baz This keywords along with mary for nosy.

----------
keyword: +Baz This, Foo
nosy: +mary
status: unread -> chatting
title: Testing... -> set keyword

_______________________________________________________________________
Roundup issue tracker <issue_tracker@your.tracker.email.domain.example>
<http://tracker.example/cgi-bin/roundup.cgi/bugs/issue1>
_______________________________________________________________________
'''        
        self.db.keyword.create(name='Foo')
        self.db.keyword.create(name='Bar')
        self.db.keyword.create(name='Baz This')

        self.db.issue.properties['keyword'].msg_header_property=''

        nodeid1 = self.doNewIssue()
        nodeid2 = self._handle_mail('''Content-Type: text/plain;
  charset="iso-8859-1"
From: "Bork, Chef" <chef@bork.bork.bork>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <followup_dummy_id>
In-Reply-To: <dummy_test_message_id>
Subject: [issue1] set keyword [ keyword =+ Foo,Baz This ; nosy =+ mary ]

Set the Foo and Baz This keywords along with mary for nosy.
''')
        assert os.path.exists(SENDMAILDEBUG)
        self.compareMessages(self._get_mail(), reference_email)


    def testOutlookAttachment(self):
        message = '''X-MimeOLE: Produced By Microsoft Exchange V6.5
Content-class: urn:content-classes:message
MIME-Version: 1.0
Content-Type: multipart/mixed;
	boundary="----_=_NextPart_001_01CACA65.40A51CBC"
Subject: Example of a failed outlook attachment e-mail
Date: Tue, 23 Mar 2010 01:43:44 -0700
Message-ID: <CA37F17219784343816CA6613D2E339205E7D0F9@nrcwstexb1.nrc.ca>
X-MS-Has-Attach: yes
X-MS-TNEF-Correlator: 
Thread-Topic: Example of a failed outlook attachment e-mail
Thread-Index: AcrKJo/t3pUBBwTpSwWNE3LE67UBDQ==
From: "Hugh" <richard@test.test>
To: <richard@test.test>
X-OriginalArrivalTime: 23 Mar 2010 08:45:57.0350 (UTC) FILETIME=[41893860:01CACA65]

This is a multi-part message in MIME format.

------_=_NextPart_001_01CACA65.40A51CBC
Content-Type: multipart/alternative;
	boundary="----_=_NextPart_002_01CACA65.40A51CBC"


------_=_NextPart_002_01CACA65.40A51CBC
Content-Type: text/plain;
	charset="us-ascii"
Content-Transfer-Encoding: quoted-printable


Hi Richard,

I suppose this isn't the exact message that was sent but is a resend of
one of my trial messages that failed.  For your benefit I changed the
subject line and am adding these words to the message body.  Should
still be as problematic, but if you like I can resend an exact copy of a
failed message changing nothing except putting your address instead of
our tracker.

Thanks very much for taking time to look into this.  Much appreciated.

 <<battery backup>>=20

------_=_NextPart_002_01CACA65.40A51CBC
Content-Type: text/html;
	charset="us-ascii"
Content-Transfer-Encoding: quoted-printable

<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2//EN">
<HTML>
<HEAD>
<META HTTP-EQUIV=3D"Content-Type" CONTENT=3D"text/html; =
charset=3Dus-ascii">
<META NAME=3D"Generator" CONTENT=3D"MS Exchange Server version =
6.5.7654.12">
<TITLE>Example of a failed outlook attachment e-mail</TITLE>
</HEAD>
<BODY>
<!-- Converted from text/rtf format -->
<BR>

<P><FONT SIZE=3D2 FACE=3D"Arial">Hi Richard,</FONT>
</P>

<P><FONT SIZE=3D2 FACE=3D"Arial">I suppose this isn't the exact message =
that was sent but is a resend of one of my trial messages that =
failed.&nbsp; For your benefit I changed the subject line and am adding =
these words to the message body.&nbsp; Should still be as problematic, =
but if you like I can resend an exact copy of a failed message changing =
nothing except putting your address instead of our tracker.</FONT></P>

<P><FONT SIZE=3D2 FACE=3D"Arial">Thanks very much for taking time to =
look into this.&nbsp; Much appreciated.</FONT>
</P>
<BR>

<P><FONT FACE=3D"Arial" SIZE=3D2 COLOR=3D"#000000"> &lt;&lt;battery =
backup&gt;&gt; </FONT>
</P>

</BODY>
</HTML>
------_=_NextPart_002_01CACA65.40A51CBC--

------_=_NextPart_001_01CACA65.40A51CBC
Content-Type: message/rfc822
Content-Transfer-Encoding: 7bit

X-MimeOLE: Produced By Microsoft Exchange V6.5
MIME-Version: 1.0
Content-Type: multipart/alternative;
	boundary="----_=_NextPart_003_01CAC15A.29717800"
X-OriginalArrivalTime: 11 Mar 2010 20:33:51.0249 (UTC) FILETIME=[28FEE010:01CAC15A]
Content-class: urn:content-classes:message
Subject: battery backup
Date: Thu, 11 Mar 2010 13:33:43 -0700
Message-ID: <p06240809c7bf02f9624c@[128.114.22.203]>
X-MS-Has-Attach: 
X-MS-TNEF-Correlator: 
Thread-Topic: battery backup
Thread-Index: AcrBWimtulTrSvBdQ2CcfZ8lyQdxmQ==
From: "Jerry" <jerry@test.test>
To: "Hugh" <hugh@test.test>

This is a multi-part message in MIME format.

------_=_NextPart_003_01CAC15A.29717800
Content-Type: text/plain;
	charset="iso-8859-1"
Content-Transfer-Encoding: quoted-printable

Dear Hugh,
	A car batter has an energy capacity of ~ 500Wh.  A UPS=20
battery is worse than this.

if we need to provied 100kW for 30 minutes that will take 100 car=20
batteries.  This seems like an awful lot of batteries.

Of course I like your idea of making the time 1 minute, so we get to=20
a more modest number of batteries

Jerry


------_=_NextPart_003_01CAC15A.29717800
Content-Type: text/html;
	charset="iso-8859-1"
Content-Transfer-Encoding: quoted-printable

<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2//EN">
<HTML>
<HEAD>
<META HTTP-EQUIV=3D"Content-Type" CONTENT=3D"text/html; =
charset=3Diso-8859-1">
<META NAME=3D"Generator" CONTENT=3D"MS Exchange Server version =
6.5.7654.12">
<TITLE>battery backup</TITLE>
</HEAD>
<BODY>
<!-- Converted from text/plain format -->

<P><FONT SIZE=3D2>Dear Hugh,</FONT>

<BR>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <FONT SIZE=3D2>A car =
batter has an energy capacity of ~ 500Wh.&nbsp; A UPS </FONT>

<BR><FONT SIZE=3D2>battery is worse than this.</FONT>
</P>

<P><FONT SIZE=3D2>if we need to provied 100kW for 30 minutes that will =
take 100 car </FONT>

<BR><FONT SIZE=3D2>batteries.&nbsp; This seems like an awful lot of =
batteries.</FONT>
</P>

<P><FONT SIZE=3D2>Of course I like your idea of making the time 1 =
minute, so we get to </FONT>

<BR><FONT SIZE=3D2>a more modest number of batteries</FONT>
</P>

<P><FONT SIZE=3D2>Jerry</FONT>
</P>

</BODY>
</HTML>
------_=_NextPart_003_01CAC15A.29717800--

------_=_NextPart_001_01CACA65.40A51CBC--
'''
        nodeid = self._handle_mail(message)
        assert not os.path.exists(SENDMAILDEBUG)
        msgid = self.db.issue.get(nodeid, 'messages')[0]
        self.assertTrue(self.db.msg.get(msgid, 'content').startswith('Hi Richard'))
        self.assertEqual(self.db.msg.get(msgid, 'files'), ['1', '2'])
        fileid = self.db.msg.get(msgid, 'files')[0]
        self.assertEqual(self.db.file.get(fileid, 'type'), 'text/html')
        fileid = self.db.msg.get(msgid, 'files')[1]
        self.assertEqual(self.db.file.get(fileid, 'type'), 'message/rfc822')

    def testForwardedMessageAttachment(self):
        message = '''Return-Path: <rgg@test.test>
Received: from localhost(127.0.0.1), claiming to be "[115.130.26.69]"
  via SMTP by localhost, id smtpdAAApLaWrq; Tue Apr 13 23:10:05 2010
Message-ID: <4BC4F9C7.50409@test.test>
Date: Wed, 14 Apr 2010 09:09:59 +1000
From: Rupert Goldie <rgg@test.test>
User-Agent: Thunderbird 2.0.0.24 (Windows/20100228)
MIME-Version: 1.0
To: ekit issues <issues@test.test>
Subject: [Fwd: PHP ERROR (fb)] post limit reached
Content-Type: multipart/mixed; boundary="------------000807090608060304010403"

This is a multi-part message in MIME format.
--------------000807090608060304010403
Content-Type: text/plain; charset=ISO-8859-1; format=flowed
Content-Transfer-Encoding: 7bit

Catch this exception and log it without emailing.

--------------000807090608060304010403
Content-Type: message/rfc822; name="PHP ERROR (fb).eml"
Content-Transfer-Encoding: 7bit
Content-Disposition: inline; filename="PHP ERROR (fb).eml"

Return-Path: <ektravj@test.test>
X-Sieve: CMU Sieve 2.2
via SMTP by crown.off.ekorp.com, id smtpdAAA1JaW1o; Tue Apr 13 23:01:04 2010
X-Virus-Scanned: by amavisd-new at ekit.com
To: facebook-errors@test.test
From: ektravj@test.test
Subject: PHP ERROR (fb)
Message-Id: <20100413230100.D601D27E84@mail2.elax3.ekorp.com>
Date: Tue, 13 Apr 2010 23:01:00 +0000 (UTC)

[13-Apr-2010 22:49:02] PHP Fatal error:  Uncaught exception 'Exception' with message 'Facebook Error Message: Feed action request limit reached' in /app/01/www/virtual/fb.ekit.com/htdocs/includes/functions.php:280
Stack trace:
#0 /app/01/www/virtual/fb.ekit.com/htdocs/gateway/ekit/feed/index.php(178): fb_exceptions(Object(FacebookRestClientException))
#1 {main}
 thrown in /app/01/www/virtual/fb.ekit.com/htdocs/includes/functions.php on line 280


--------------000807090608060304010403--
'''
        nodeid = self._handle_mail(message)
        assert not os.path.exists(SENDMAILDEBUG)
        msgid = self.db.issue.get(nodeid, 'messages')[0]
        self.assertEqual(self.db.msg.get(msgid, 'content'),
            'Catch this exception and log it without emailing.')
        self.assertEqual(self.db.msg.get(msgid, 'files'), ['1'])
        fileid = self.db.msg.get(msgid, 'files')[0]
        self.assertEqual(self.db.file.get(fileid, 'type'), 'message/rfc822')


    def testStandardMsg(self):
        self.instance.config['MAIL_DOMAIN'] = 'example.com'
        name = u'Accented chars \xe4\xf6\xfc\xc4\xd6\xdc\xdf'
        # Python2 wants an UTF-8 string in first component of adr and content
        # while Python3 wants a String
        # It *may* be a bug that the subject can be Unicode in python2.
        # But it doesn't hurt if the encoding happens to be utf-8
        if sys.version_info[0] <= 2:
            name = name.encode('utf-8')
        adr  = 'someone@example.com'
        to   = [adr]
        adr  = (name, adr)
        mailer = roundupdb.Mailer(self.db.config)
        mailer.standard_message(to, subject=name, content=name, author=adr)
        assert os.path.exists(SENDMAILDEBUG)
        self.compareMessages(self._get_mail(),
'''
FROM: roundup-admin@example.com
TO: someone@example.com
From: =?utf-8?b?QWNjZW50ZWQgY2hhcnMgw6TDtsO8w4TDlsOcw58=?=
 <someone@example.com>
To: someone@example.com
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Subject: =?utf-8?b?QWNjZW50ZWQgY2hhcnMgw6TDtsO8w4TDlsOcw58=?=
X-Roundup-Name: Roundup issue tracker
X-Roundup-Loop: hello
Content-Transfer-Encoding: base64

QWNjZW50ZWQgY2hhcnMgw6TDtsO8w4TDlsOcw58=
''')


@skip_pgp
class MailgwPGPTestCase(MailgwTestAbstractBase, unittest.TestCase):
    pgphome = gpgmelib.pgphome
    def setUp(self):
        MailgwTestAbstractBase.setUp(self)
        self.db.security.addRole(name = 'pgp', description = 'PGP Role')
        self.instance.config['PGP_HOMEDIR'] = self.pgphome
        self.instance.config['PGP_ROLES'] = 'pgp'
        self.instance.config['PGP_ENABLE'] = True
        self.instance.config['MAIL_DOMAIN'] = 'example.com'
        self.instance.config['ADMIN_EMAIL'] = 'roundup-admin@example.com'
        self.db.user.set(self.john_id, roles='User,pgp')
        gpgmelib.setUpPGP()

    def tearDown(self):
        MailgwTestAbstractBase.tearDown(self)
        gpgmelib.tearDownPGP()

    def testPGPUnsignedMessage(self):
        self.assertRaises(MailUsageError, self._handle_mail,
            '''Content-Type: text/plain;
  charset="iso-8859-1"
From: John Doe <john@test.test>
To: issue_tracker@your.tracker.email.domain.example
Message-Id: <dummy_test_message_id>
Subject: [issue] Testing non-signed message...

This is no pgp signed message.
''')

    signed_msg = '''Content-Disposition: inline
From: John Doe <john@test.test>
To: issue_tracker@your.tracker.email.domain.example
Subject: [issue] Testing signed message...
Content-Type: multipart/signed; micalg=pgp-sha1;
        protocol="application/pgp-signature"; boundary="cWoXeonUoKmBZSoM"


--cWoXeonUoKmBZSoM
Content-Type: text/plain; charset=us-ascii
Content-Disposition: inline

This is a pgp signed message.

--cWoXeonUoKmBZSoM
Content-Type: application/pgp-signature; name="signature.asc"
Content-Description: Digital signature
Content-Disposition: inline

-----BEGIN PGP SIGNATURE-----
Version: GnuPG v1.4.10 (GNU/Linux)

iJwEAQECAAYFAk6N4A4ACgkQv8+6oPhbo5x5nAP/d7R7SxTvLoVESI+1r7eDXp1J
LvBVU2EF3YFYKBHMLcWmjG92fNjnHX6NENTEhTeBynba5IPEwUfITC+7PmgPmQkA
VXnFZnwraHxsYgyFsVFN1kkTSbwRUlWl9+nTEsr0yBLTpZN0QSIDcwu+i/xVcg+t
ZQ4K6R3m3AOw7BLdvZs=
=wpYk
-----END PGP SIGNATURE-----

--cWoXeonUoKmBZSoM--
'''

    def testPGPSignedMessage(self):
        nodeid = self._handle_mail(self.signed_msg)
        m = self.db.issue.get(nodeid, 'messages')[0]
        self.assertEqual(self.db.msg.get(m, 'content'), 
            'This is a pgp signed message.')
        # check that the message has the right source code
        l = self.db.msg.get(m, 'tx_Source')
        self.assertEqual(l, 'email-sig-openpgp')


    def testPGPSignedMessageFail(self):
        # require both, signing and encryption
        self.instance.config['PGP_REQUIRE_INCOMING'] = 'both'
        self.assertRaises(MailUsageError, self._handle_mail, self.signed_msg)

    encrypted_msg = '''Content-Disposition: inline
From: John Doe <john@test.test>
To: roundup-admin@example.com
Subject: [issue] Testing encrypted message...
Content-Type: multipart/encrypted; protocol="application/pgp-encrypted";
        boundary="d6Gm4EdcadzBjdND"

--d6Gm4EdcadzBjdND
Content-Type: application/pgp-encrypted
Content-Disposition: attachment

Version: 1

--d6Gm4EdcadzBjdND
Content-Type: application/octet-stream
Content-Disposition: inline; filename="msg.asc"

-----BEGIN PGP MESSAGE-----
Version: GnuPG v1.4.10 (GNU/Linux)

hQEMAzfeQttq+Q2YAQf9FxCtZVgC7jAy6UkeAJ1imCpnh9DgKA5w40OFtrY4mVAp
cL7kCkvGvJCW7uQZrmSgIiYaZGLI3GS42XutORC6E6PzBEW0fJUMIXYmoSd0OFeY
3H2+854qu37W/uCOWM9OnPFIH8g8q8DgYy88i0goM+Ot9Q96yFfJ7QymanOZJgVa
MNC+oKDiIZKiE3PCwtGr+8CHZN/9J6O4FeJijBlr09C5LXc+Nif5T0R0nt17MAns
9g2UvGxW8U24NAS1mOg868U05hquLPIcFz9jGZGknJu7HBpOkQ9GjKqkzN8pgZVN
VbN8IdDqi0QtRKE44jtWQlyNlESMjv6GtC2V9F6qKNK8AfHtBexDhyv4G9cPFFNO
afQ6e4dPi89RYIQyydtwiqao8fj6jlAy2Z1cbr7YxwBG7BeUZv9yis7ShaAIo78S
82MrCYpSjfHNwKiSfC5yITw22Uv4wWgixVdAsaSdtBqEKXJPG9LNey18ArsBjSM1
P81iDOWUp/uyIe5ZfvNI38BBxEYslPTUlDk2GB8J2Vun7IWHoj9a4tY3IotC9jBr
5Qnigzqrt7cJZX6OrN0c+wnOjXbMGYXmgSs4jeM=
=XX5Q
-----END PGP MESSAGE-----

--d6Gm4EdcadzBjdND--
'''
    def testPGPEncryptedUnsignedMessageError(self):
        self.assertRaises(MailUsageError, self._handle_mail, self.encrypted_msg)

    def testPGPEncryptedUnsignedMessage(self):
        # no error if we don't require a signature:
        self.instance.config['PGP_REQUIRE_INCOMING'] = 'encrypted'
        nodeid = self._handle_mail (self.encrypted_msg)
        m = self.db.issue.get(nodeid, 'messages')[0]
        self.assertEqual(self.db.msg.get(m, 'content'), 
            'This is the text to be encrypted')
        # check that the message has the right source code
        l = self.db.msg.get(m, 'tx_Source')
        self.assertEqual(l, 'email')

    def testPGPEncryptedUnsignedMessageFromNonPGPUser(self):
        msg = self.encrypted_msg.replace('John Doe <john@test.test>',
            '"Contrary, Mary" <mary@test.test>')
        nodeid = self._handle_mail (msg)
        m = self.db.issue.get(nodeid, 'messages')[0]
        self.assertEqual(self.db.msg.get(m, 'content'), 
            'This is the text to be encrypted')
        self.assertEqual(self.db.msg.get(m, 'author'), self.mary_id)
        # check that the message has the right source code
        l = self.db.msg.get(m, 'tx_Source')
        self.assertEqual(l, 'email')


    # check that a bounce-message that is triggered *after*
    # decrypting is properly encrypted:
    def testPGPEncryptedUnsignedMessageCheckBounce(self):
        # allow non-signed msg
        self.instance.config['PGP_REQUIRE_INCOMING'] = 'encrypted'
        # don't allow creation of message, trigger error *after* decrypt
        self.db.user.set(self.john_id, roles='pgp')
        self.db.security.addPermissionToRole('pgp', 'Email Access')
        self.db.security.addPermissionToRole('pgp', 'Create', 'issue')
        # trap_exc=1: we want a bounce message:
        self._handle_mail(self.encrypted_msg, trap_exc=1)
        m = self._get_mail()
        parts = email.message_from_string(m).get_payload()
        self.assertEqual(len(parts),2)
        self.assertEqual(parts[0].get_payload().strip(), 'Version: 1')
        crypt = gpg.core.Data(parts[1].get_payload())
        plain = gpg.core.Data()
        ctx = gpg.core.Context()
        res = ctx.op_decrypt(crypt, plain)
        self.assertEqual(res, None)
        plain.seek(0,0)
        parts = message_from_bytes(plain.read()).get_payload()
        self.assertEqual(len(parts),2)
        self.assertEqual(parts[0].get_payload().strip(),
            'You are not permitted to create messages.')
        self.assertEqual(parts[1].get_payload().strip(),
            '''Content-Type: text/plain; charset=us-ascii
Content-Disposition: inline

This is the text to be encrypted''')


    def testPGPEncryptedSignedMessage(self):
        # require both, signing and encryption
        self.instance.config['PGP_REQUIRE_INCOMING'] = 'both'
        nodeid = self._handle_mail('''Content-Disposition: inline
From: John Doe <john@test.test>
To: roundup-admin@example.com
Subject: Testing encrypted and signed message
MIME-Version: 1.0
Content-Type: multipart/encrypted; protocol="application/pgp-encrypted";
        boundary="ReaqsoxgOBHFXBhH"

--ReaqsoxgOBHFXBhH
Content-Type: application/pgp-encrypted
Content-Disposition: attachment

Version: 1

--ReaqsoxgOBHFXBhH
Content-Type: application/octet-stream
Content-Disposition: inline; filename="msg.asc"

-----BEGIN PGP MESSAGE-----
Version: GnuPG v1.4.10 (GNU/Linux)

hQEMAzfeQttq+Q2YAQf+NaC3r8qBURQqxHH9IAP4vg0QAP2yj3n0v6guo1lRf5BA
EUfTQ3jc3chxLvzTgoUIuMOvhlNroqR1lgLwhfSTCyuKWDZa+aVNiSgsB2MD44Xd
mAkKKmnmOGLmfbICbPQZxl4xNhCMTHiAy1xQE6mTj/+pEAq5XxjJUwn/gJ3O1Wmd
NyWtJY2N+TRbxUVB2WhG1j9J1D2sjhG26TciE8JeuLDZzaiVNOW9YlX2Lw5KtlkR
Hkgw6Xme06G0XXZUcm9JuBU/7oFP/tSrC1tBsnVlq1pZYf6AygIBdXWb9gD/WmXh
7Eu/xCKrw4RFnXnTgmBz/NHRfVDkfdSscZqexnG1D9LAwQHSuVf8sxDPNesv0W+8
e49loVjvU+Y0BCFQAbWSW4iOEUYZpW/ITRE4+wIqMXZbAraeBV0KPZ4hAa3qSmf+
oZBRcbzssL163Odx/OHRuK2J2CHC654+crrlTBnxd/RUKgRbSUKwrZzB2G6OPcGv
wfiqXsY+XvSZtTbWuvUJxePh8vhhhjpuo1JtlrYc3hZ9OYgoCoV1JiLl5c60U5Es
oUT9GDl1Qsgb4dF4TJ1IBj+riYiocYpJxPhxzsy6liSLNy2OA6VEjG0FGk53+Ok9
7UzOA+WaHJHSXafZzrdP1TWJUFlOMA+dOgTKpH69eL1+IRfywOjEwp1UNSbLnJpc
D0QQLwIFttplKvYkn0DZByJCVnIlGkl4s5LM5rnc8iecX8Jad0iRIlPV6CVM+Nso
WdARUfyJfXAmz8uk4f2sVfeMu1gdMySdjvxwlgHDJdBPIG51r2b8L/NCTiC57YjF
zGhS06FLl3V1xx6gBlpqQHjut3efrAGpXGBVpnTJMOcgYAk=
=jt/n
-----END PGP MESSAGE-----

--ReaqsoxgOBHFXBhH--
''')
        m = self.db.issue.get(nodeid, 'messages')[0]
        self.assertEqual(self.db.msg.get(m, 'content'), 
            'This is the text of a signed and encrypted email.')
        # check that the message has the right source code
        l = self.db.msg.get(m, 'tx_Source')
        self.assertEqual(l, 'email-sig-openpgp')

# vim: set filetype=python sts=4 sw=4 et si :
