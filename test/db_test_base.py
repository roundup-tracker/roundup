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

from __future__ import print_function
import unittest, os, shutil, errno, sys, time, pprint, os.path

try:
    from base64 import encodebytes as base64_encode  # python3 only
except ImportError:
    # python2 and deplricated in 3
    from base64 import encodestring as base64_encode

import logging, cgi
from . import gpgmelib
from email import message_from_string

import pytest
from roundup.hyperdb import String, Password, Link, Multilink, Date, \
    Interval, DatabaseError, Boolean, Number, Node, Integer
from roundup.mailer import Mailer
from roundup import date, password, init, instance, configuration, \
    roundupdb, i18n, hyperdb
from roundup.cgi.templating import HTMLItem
from roundup.cgi.templating import HTMLProperty, _HTMLItem, anti_csrf_nonce
from roundup.cgi import client, actions
from roundup.cgi.engine_zopetal import RoundupPageTemplate
from roundup.cgi.templating import HTMLItem
from roundup.exceptions import UsageError, Reject

from roundup.anypy.strings import b2s, s2b, u2s
from roundup.anypy.cmp_ import NoneAndDictComparable
from roundup.anypy.email_ import message_from_bytes

from roundup.test.mocknull import MockNull

config = configuration.CoreConfig()
config.DATABASE = "db"
config.RDBMS_NAME = "rounduptest"
config.RDBMS_HOST = "localhost"
config.RDBMS_USER = "rounduptest"
config.RDBMS_PASSWORD = "rounduptest"
config.RDBMS_TEMPLATE = "template0"
# these TRACKER_WEB and MAIL_DOMAIN values are used in mailgw tests
config.MAIL_DOMAIN = "your.tracker.email.domain.example"
config.TRACKER_WEB = "http://tracker.example/cgi-bin/roundup.cgi/bugs/"
# uncomment the following to have excessive debug output from test cases
# FIXME: tracker logging level should be increased by -v arguments
#   to 'run_tests.py' script
#config.LOGGING_FILENAME = "/tmp/logfile"
#config.LOGGING_LEVEL = "DEBUG"
config.init_logging()

def setupTracker(dirname, backend="anydbm", optimize=False):
    """Install and initialize new tracker in dirname; return tracker instance.

    If the directory exists, it is wiped out before the operation.

    """
    global config
    try:
        shutil.rmtree(dirname)
    except OSError as error:
        if error.errno not in (errno.ENOENT, errno.ESRCH): raise
    # create the instance
    init.install(dirname, os.path.join(os.path.dirname(__file__),
                                       '..',
                                       'share',
                                       'roundup',
                                       'templates',
                                       'classic'))
    config.RDBMS_BACKEND = backend
    config.save(os.path.join(dirname, 'config.ini'))
    tracker = instance.open(dirname, optimize=optimize)
    if tracker.exists():
        tracker.nuke()
    tracker.init(password.Password('sekrit'))
    return tracker

def setupSchema(db, create, module):
    mls = module.Class(db, "mls", name=String())
    mls.setkey("name")
    keyword = module.Class(db, "keyword", name=String(), order=Number())
    keyword.setkey("name")
    status = module.Class(db, "status", name=String(), mls=Multilink("mls"))
    status.setkey("name")
    priority = module.Class(db, "priority", name=String(), order=String())
    priority.setkey("name")
    user = module.Class(db, "user", username=String(),
        password=Password(quiet=True), assignable=Boolean(quiet=True),
        age=Number(quiet=True), roles=String(), address=String(),
        rating=Integer(quiet=True), supervisor=Link('user'),
        realname=String(quiet=True), longnumber=Number(use_double=True))
    user.setkey("username")
    file = module.FileClass(db, "file", name=String(), type=String(),
        comment=String(indexme="yes"), fooz=Password())
    file_nidx = module.FileClass(db, "file_nidx", content=String(indexme='no'))

    # initialize quiet mode a second way without using Multilink("user", quiet=True)
    mynosy = Multilink("user", rev_multilink='nosy_issues')
    mynosy.quiet = True
    issue = module.IssueClass(db, "issue", title=String(indexme="yes"),
        status=Link("status"), nosy=mynosy, deadline=Date(quiet=True),
        foo=Interval(quiet=True, default_value=date.Interval('-1w')),
        files=Multilink("file"), assignedto=Link('user', quiet=True,
        rev_multilink='issues'), priority=Link('priority'),
        spam=Multilink('msg'), feedback=Link('msg'),
        keywords=Multilink('keyword'), keywords2=Multilink('keyword'))
    stuff = module.Class(db, "stuff", stuff=String())
    session = module.Class(db, 'session', title=String())
    msg = module.FileClass(db, "msg", date=Date(),
        author=Link("user", do_journal='no'), files=Multilink('file'),
        inreplyto=String(), messageid=String(),
        recipients=Multilink("user", do_journal='no'))
    session.disableJournalling()
    db.post_init()
    if create:
        user.create(username="admin", roles='Admin',
            password=password.Password('sekrit'))
        user.create(username="fred", roles='User',
            password=password.Password('sekrit'), address='fred@example.com')
        u1 = mls.create(name="unread_1")
        u2 = mls.create(name="unread_2")
        status.create(name="unread",mls=[u1, u2])
        status.create(name="in-progress")
        status.create(name="testing")
        status.create(name="resolved")
        priority.create(name="feature", order="2")
        priority.create(name="wish", order="3")
        priority.create(name="bug", order="1")
    db.commit()

    # nosy tests require this
    db.security.addPermissionToRole('User', 'View', 'msg')

    # quiet journal tests require this
    # QuietJournal - reference used later in tests
    v1 = db.security.addPermission(name='View', klass='user',
                properties=['username', 'supervisor', 'assignable'],
                description="Prevent users from seeing roles")

    db.security.addPermissionToRole("User", v1)

class MyTestCase(object):
    def tearDown(self):
        if hasattr(self, 'db'):
            self.db.close()
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)

    def open_database(self, user='admin'):
        self.db = self.module.Database(config, user)


if 'LOGGING_LEVEL' in os.environ:
    logger = logging.getLogger('roundup.hyperdb')
    logger.setLevel(os.environ['LOGGING_LEVEL'])

class commonDBTest(MyTestCase):
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.open_database()
        setupSchema(self.db, 1, self.module)

    def iterSetup(self, classname='issue'):
        cls = getattr(self.db, classname)
        def filt_iter_list(*args, **kw):
            """ for checking equivalence of filter and filter_iter """
            return list(cls.filter_iter(*args, **kw))
        def filter_test_iterator():
            """ yield all filter variants with config settings changed
                appropriately
            """
            self.db.config.RDBMS_SERVERSIDE_CURSOR = False
            yield (cls.filter)
            yield (filt_iter_list)
            self.db.config.RDBMS_SERVERSIDE_CURSOR = True
            yield (cls.filter)
            yield (filt_iter_list)
        return self.assertEqual, filter_test_iterator

    def filteringSetupTransitiveSearch(self, classname='issue'):
        u_m = {}
        k = 30
        for user in (
                {'username': 'ceo', 'age': 129},
                {'username': 'grouplead1', 'age': 29, 'supervisor': '3'},
                {'username': 'grouplead2', 'age': 29, 'supervisor': '3'},
                {'username': 'worker1', 'age': 25, 'supervisor' : '4'},
                {'username': 'worker2', 'age': 24, 'supervisor' : '4'},
                {'username': 'worker3', 'age': 23, 'supervisor' : '5'},
                {'username': 'worker4', 'age': 22, 'supervisor' : '5'},
                {'username': 'worker5', 'age': 21, 'supervisor' : '5'}):
            u = self.db.user.create(**user)
            u_m [u] = self.db.msg.create(author = u, content = ' '
                , date = date.Date ('2006-01-%s' % k))
            k -= 1
        i = date.Interval('-1d')
        for issue in (
                {'title': 'ts1', 'status': '2', 'assignedto': '6',
                    'priority': '3', 'messages' : [u_m ['6']], 'nosy' : ['4']},
                {'title': 'ts2', 'status': '1', 'assignedto': '6',
                    'priority': '3', 'messages' : [u_m ['6']], 'nosy' : ['5']},
                {'title': 'ts4', 'status': '2', 'assignedto': '7',
                    'priority': '3', 'messages' : [u_m ['7']]},
                {'title': 'ts5', 'status': '1', 'assignedto': '8',
                    'priority': '3', 'messages' : [u_m ['8']]},
                {'title': 'ts6', 'status': '2', 'assignedto': '9',
                    'priority': '3', 'messages' : [u_m ['9']]},
                {'title': 'ts7', 'status': '1', 'assignedto': '10',
                    'priority': '3', 'messages' : [u_m ['10']]},
                {'title': 'ts8', 'status': '2', 'assignedto': '10',
                    'priority': '3', 'messages' : [u_m ['10']], 'foo' : i},
                {'title': 'ts9', 'status': '1', 'assignedto': '10',
                    'priority': '3', 'messages' : [u_m ['10'], u_m ['9']]}):
            self.db.issue.create(**issue)
        return self.iterSetup(classname)


class DBTest(commonDBTest):

    @pytest.fixture(autouse=True)
    def inject_fixtures(self, caplog):
        self._caplog = caplog

    def testRefresh(self):
        self.db.refresh_database()

    
    def testUpgrade_5_to_6(self):

        if(self.db.dbtype in ['anydbm', 'memorydb']):
           self.skipTest('No schema upgrade needed on non rdbms backends')

        # load the database
        self.db.issue.create(title="flebble frooz")
        self.db.commit()

        self.assertEqual(self.db.database_schema['version'], 6,
                         "This test only runs for database version 6")
        self.db.database_schema['version'] = 5
        if self.db.dbtype == 'mysql':
            # version 6 has 5 indexes
            self.db.sql('show indexes from _user;')
            self.assertEqual(5,len(self.db.cursor.fetchall()),
                             "Database created with wrong number of indexes")

            self.drop_key_retired_idx()

            # after dropping (key.__retired__) composite index we have
            # 3 index entries
            self.db.sql('show indexes from _user;')
            self.assertEqual(3,len(self.db.cursor.fetchall()))

            # test upgrade adding index
            self.db.post_init()

            # they're back
            self.db.sql('show indexes from _user;')
            self.assertEqual(5,len(self.db.cursor.fetchall()))

            # test a database already upgraded from 4 to 5
            # so it has the index to enforce key uniqueness
            self.db.database_schema['version'] = 5
            self.db.post_init()

            # they're still here.
            self.db.sql('show indexes from _user;')
            self.assertEqual(5,len(self.db.cursor.fetchall()))
        else:
            # this should be a no-op
            # test upgrade
            self.db.post_init()

    def drop_key_retired_idx(self):
        c = self.db.cursor
        for cn, klass in self.db.classes.items():
            if klass.key:
                sql = '''drop index _%s_key_retired_idx on _%s''' % (cn, cn)
                self.db.sql(sql)

    #
    # automatic properties (well, the two easy ones anyway)
    #
    def testCreatorProperty(self):
        i = self.db.issue
        id1 = i.create(title='spam')
        self.db.journaltag = 'fred'
        id2 = i.create(title='spam')
        self.assertNotEqual(id1, id2)
        self.assertNotEqual(i.get(id1, 'creator'), i.get(id2, 'creator'))

    def testActorProperty(self):
        i = self.db.issue
        id1 = i.create(title='spam')
        self.db.journaltag = 'fred'
        i.set(id1, title='asfasd')
        self.assertNotEqual(i.get(id1, 'creator'), i.get(id1, 'actor'))

    # ID number controls
    def testIDGeneration(self):
        id1 = self.db.issue.create(title="spam", status='1')
        id2 = self.db.issue.create(title="eggs", status='2')
        self.assertNotEqual(id1, id2)
    def testIDSetting(self):
        # XXX numeric ids
        self.db.setid('issue', 10)
        id2 = self.db.issue.create(title="eggs", status='2')
        self.assertEqual('11', id2)

    #
    # basic operations
    #
    def testEmptySet(self):
        id1 = self.db.issue.create(title="spam", status='1')
        self.db.issue.set(id1)

    # String
    def testStringChange(self):
        for commit in (0,1):
            # test set & retrieve
            nid = self.db.issue.create(title="spam", status='1')
            self.assertEqual(self.db.issue.get(nid, 'title'), 'spam')

            # change and make sure we retrieve the correct value
            self.db.issue.set(nid, title='eggs')
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, 'title'), 'eggs')

    def testStringUnset(self):
        for commit in (0,1):
            nid = self.db.issue.create(title="spam", status='1')
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, 'title'), 'spam')
            # make sure we can unset
            self.db.issue.set(nid, title=None)
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "title"), None)

    # FileClass "content" property (no unset test)
    def testFileClassContentChange(self):
        for commit in (0,1):
            # test set & retrieve
            nid = self.db.file.create(content="spam")
            self.assertEqual(self.db.file.get(nid, 'content'), 'spam')

            # change and make sure we retrieve the correct value
            self.db.file.set(nid, content='eggs')
            if commit: self.db.commit()
            self.assertEqual(self.db.file.get(nid, 'content'), 'eggs')

    def testStringUnicode(self):
        # test set & retrieve
        ustr = u2s(u'\xe4\xf6\xfc\u20ac')
        nid = self.db.issue.create(title=ustr, status='1')
        self.assertEqual(self.db.issue.get(nid, 'title'), ustr)

        # change and make sure we retrieve the correct value
        ustr2 = u2s(u'change \u20ac change')
        self.db.issue.set(nid, title=ustr2)
        self.db.commit()
        self.assertEqual(self.db.issue.get(nid, 'title'), ustr2)

        # test set & retrieve (this time for file contents)
        nid = self.db.file.create(content=ustr)
        self.assertEqual(self.db.file.get(nid, 'content'), ustr)
        self.assertEqual(self.db.file.get(nid, 'binary_content'), s2b(ustr))

    def testStringBinary(self):
        ''' Create file with binary content that is not able
            to be interpreted as unicode. Try to cause file module
            trigger and handle UnicodeDecodeError
            and get valid output
        '''
        # test set & retrieve
        bstr = b'\x00\xF0\x34\x33' # random binary data

        # test set & retrieve (this time for file contents)
        nid = self.db.file.create(content=bstr)
        print(nid)
        print(repr(self.db.file.get(nid, 'content')))
        print(repr(self.db.file.get(nid, 'binary_content')))
        p3val='file1 is not text, retrieve using binary_content property. mdsum: 0e1d1b47e4bd1beab3afc9b79f596c1d'

        if sys.version_info[0] > 2:
            # python 3
            self.assertEqual(self.db.file.get(nid, 'content'), p3val)
            self.assertEqual(self.db.file.get(nid, 'binary_content'),
                             bstr)
        else:
            # python 2
            self.assertEqual(self.db.file.get(nid, 'content'), bstr)
            self.assertEqual(self.db.file.get(nid, 'binary_content'), bstr)

    # Link
    def testLinkChange(self):
        self.assertRaises(IndexError, self.db.issue.create, title="spam",
            status='100')
        for commit in (0,1):
            nid = self.db.issue.create(title="spam", status='1')
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "status"), '1')
            self.db.issue.set(nid, status='2')
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "status"), '2')

    def testLinkUnset(self):
        for commit in (0,1):
            nid = self.db.issue.create(title="spam", status='1')
            if commit: self.db.commit()
            self.db.issue.set(nid, status=None)
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "status"), None)

    # Multilink
    def testMultilinkChange(self):
        for commit in (0,1):
            self.assertRaises(IndexError, self.db.issue.create, title="spam",
                nosy=['foo%s'%commit])
            u1 = self.db.user.create(username='foo%s'%commit)
            u2 = self.db.user.create(username='bar%s'%commit)
            nid = self.db.issue.create(title="spam", nosy=[u1])
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "nosy"), [u1])
            self.db.issue.set(nid, nosy=[])
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "nosy"), [])
            self.db.issue.set(nid, nosy=[u1,u2])
            if commit: self.db.commit()
            l = [u1,u2]; l.sort()
            m = self.db.issue.get(nid, "nosy"); m.sort()
            self.assertEqual(l, m)

            # verify that when we pass None to an Multilink it sets
            # it to an empty list
            self.db.issue.set(nid, nosy=None)
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "nosy"), [])

    def testMakeSeveralMultilinkedNodes(self):
        for commit in (0,1):
            u1 = self.db.user.create(username='foo%s'%commit)
            u2 = self.db.user.create(username='bar%s'%commit)
            u3 = self.db.user.create(username='baz%s'%commit)
            nid = self.db.issue.create(title="spam", nosy=[u1])
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "nosy"), [u1])
            self.db.issue.set(nid, deadline=date.Date('.'))
            self.db.issue.set(nid, nosy=[u1,u2], title='ta%s'%commit)
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "nosy"), [u1,u2])
            self.db.issue.set(nid, deadline=date.Date('.'))
            self.db.issue.set(nid, nosy=[u1,u2,u3], title='tb%s'%commit)
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "nosy"), [u1,u2,u3])

    def testMultilinkChangeIterable(self):
        for commit in (0,1):
            # invalid nosy value assertion
            self.assertRaises(IndexError, self.db.issue.create, title='spam',
                nosy=['foo%s'%commit])
            # invalid type for nosy create
            self.assertRaises(TypeError, self.db.issue.create, title='spam',
                nosy=1)
            u1 = self.db.user.create(username='foo%s'%commit)
            u2 = self.db.user.create(username='bar%s'%commit)
            # try a couple of the built-in iterable types to make
            # sure that we accept them and handle them properly
            # try a set as input for the multilink
            nid = self.db.issue.create(title="spam", nosy=set(u1))
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "nosy"), [u1])
            self.assertRaises(TypeError, self.db.issue.set, nid,
                nosy='invalid type')
            # test with a tuple
            self.db.issue.set(nid, nosy=tuple())
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "nosy"), [])
            # make sure we accept a frozen set
            self.db.issue.set(nid, nosy=set([u1,u2]))
            if commit: self.db.commit()
            l = [u1,u2]; l.sort()
            m = self.db.issue.get(nid, "nosy"); m.sort()
            self.assertEqual(l, m)


# XXX one day, maybe...
    def testMultilinkOrdering(self):
        for i in range(10):
            self.db.user.create(username='foo%s'%i)
        i = self.db.issue.create(title="spam", nosy=['5','3','12','4'])
        self.db.commit()
        l = self.db.issue.get(i, "nosy")
        # all backends should return the Multilink numeric-id-sorted
        self.assertEqual(l, ['3', '4', '5', '12'])

    # Date
    def testDateChange(self):
        self.assertRaises(TypeError, self.db.issue.create,
            title='spam', deadline=1)
        for commit in (0,1):
            nid = self.db.issue.create(title="spam", status='1')
            self.assertRaises(TypeError, self.db.issue.set, nid, deadline=1)
            a = self.db.issue.get(nid, "deadline")
            if commit: self.db.commit()
            self.db.issue.set(nid, deadline=date.Date())
            b = self.db.issue.get(nid, "deadline")
            if commit: self.db.commit()
            self.assertNotEqual(a, b)
            self.assertNotEqual(b, date.Date('1970-1-1.00:00:00'))
            # The 1970 date will fail for metakit -- it is used
            # internally for storing NULL. The others would, too
            # because metakit tries to convert date.timestamp to an int
            # for storing and fails with an overflow.
            for d in [date.Date (x) for x in ('2038', '1970', '0033', '9999')]:
                self.db.issue.set(nid, deadline=d)
                if commit: self.db.commit()
                c = self.db.issue.get(nid, "deadline")
                self.assertEqual(c, d)

    def testDateLeapYear(self):
        nid = self.db.issue.create(title='spam', status='1',
            deadline=date.Date('2008-02-29'))
        self.assertEqual(str(self.db.issue.get(nid, 'deadline')),
            '2008-02-29.00:00:00')
        self.assertEqual(self.db.issue.filter(None,
            {'deadline': '2008-02-29'}), [nid])
        self.assertEqual(list(self.db.issue.filter_iter(None,
            {'deadline': '2008-02-29'})), [nid])
        self.db.issue.set(nid, deadline=date.Date('2008-03-01'))
        self.assertEqual(str(self.db.issue.get(nid, 'deadline')),
            '2008-03-01.00:00:00')
        self.assertEqual(self.db.issue.filter(None,
            {'deadline': '2008-02-29'}), [])
        self.assertEqual(list(self.db.issue.filter_iter(None,
            {'deadline': '2008-02-29'})), [])

    def testDateUnset(self):
        for commit in (0,1):
            nid = self.db.issue.create(title="spam", status='1')
            self.db.issue.set(nid, deadline=date.Date())
            if commit: self.db.commit()
            self.assertNotEqual(self.db.issue.get(nid, "deadline"), None)
            self.db.issue.set(nid, deadline=None)
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "deadline"), None)

    def testDateSort(self):
        d1 = date.Date('.')
        ae, iiter = self.filteringSetup()
        nid = self.db.issue.create(title="nodeadline", status='1')
        self.db.commit()
        for filt in iiter():
            ae(filt(None, {}, ('+','deadline')), ['5', '2', '1', '3', '4'])
            ae(filt(None, {}, ('+','id'), ('+', 'deadline')),
                ['5', '2', '1', '3', '4'])
            ae(filt(None, {}, ('-','id'), ('-', 'deadline')),
                ['4', '3', '1', '2', '5'])

    def testDateSortMultilink(self):
        d1 = date.Date('.')
        ae, iiter = self.filteringSetup()
        nid = self.db.issue.create(title="nodeadline", status='1')
        self.db.commit()
        ae(sorted(self.db.issue.get('1','nosy')), [])
        ae(sorted(self.db.issue.get('2','nosy')), [])
        ae(sorted(self.db.issue.get('3','nosy')), ['1','2'])
        ae(sorted(self.db.issue.get('4','nosy')), ['1','2','3'])
        ae(sorted(self.db.issue.get('5','nosy')), [])
        ae(self.db.user.get('1','username'), 'admin')
        ae(self.db.user.get('2','username'), 'fred')
        ae(self.db.user.get('3','username'), 'bleep')
        # filter_iter currently doesn't work for Multilink sort
        # so testing only filter
        for f in iiter():
            if f.__name__ != 'filter':
                continue
            ae(f(None, {}, ('+', 'id'), ('+','nosy')),
                ['1', '2', '5', '4', '3'])
            ae(f(None, {}, ('+','deadline'), ('+', 'nosy')),
                ['5', '2', '1', '4', '3'])
            ae(f(None, {}, ('+','nosy'), ('+', 'deadline')),
                ['5', '2', '1', '3', '4'])

    # Interval
    def testIntervalChange(self):
        self.assertRaises(TypeError, self.db.issue.create,
            title='spam', foo=1)
        for commit in (0,1):
            nid = self.db.issue.create(title="spam", status='1')
            self.assertRaises(TypeError, self.db.issue.set, nid, foo=1)
            if commit: self.db.commit()
            a = self.db.issue.get(nid, "foo")
            i = date.Interval('-1d')
            self.db.issue.set(nid, foo=i)
            if commit: self.db.commit()
            self.assertNotEqual(self.db.issue.get(nid, "foo"), a)
            self.assertEqual(i, self.db.issue.get(nid, "foo"))
            j = date.Interval('1y')
            self.db.issue.set(nid, foo=j)
            if commit: self.db.commit()
            self.assertNotEqual(self.db.issue.get(nid, "foo"), i)
            self.assertEqual(j, self.db.issue.get(nid, "foo"))

    def testIntervalUnset(self):
        for commit in (0,1):
            nid = self.db.issue.create(title="spam", status='1')
            self.db.issue.set(nid, foo=date.Interval('-1d'))
            if commit: self.db.commit()
            self.assertNotEqual(self.db.issue.get(nid, "foo"), None)
            self.db.issue.set(nid, foo=None)
            if commit: self.db.commit()
            self.assertEqual(self.db.issue.get(nid, "foo"), None)

    # Boolean
    def testBooleanSet(self):
        nid = self.db.user.create(username='one', assignable=1)
        self.assertEqual(self.db.user.get(nid, "assignable"), 1)
        nid = self.db.user.create(username='two', assignable=0)
        self.assertEqual(self.db.user.get(nid, "assignable"), 0)

    def testBooleanChange(self):
        userid = self.db.user.create(username='foo', assignable=1)
        self.assertEqual(1, self.db.user.get(userid, 'assignable'))
        self.db.user.set(userid, assignable=0)
        self.assertEqual(self.db.user.get(userid, 'assignable'), 0)
        self.db.user.set(userid, assignable=1)
        self.assertEqual(self.db.user.get(userid, 'assignable'), 1)

    def testBooleanUnset(self):
        nid = self.db.user.create(username='foo', assignable=1)
        self.db.user.set(nid, assignable=None)
        self.assertEqual(self.db.user.get(nid, "assignable"), None)

    # Number
    def testNumberChange(self):
        nid = self.db.user.create(username='foo', age=1)
        self.assertEqual(1, self.db.user.get(nid, 'age'))
        self.db.user.set(nid, age=3)
        self.assertNotEqual(self.db.user.get(nid, 'age'), 1)
        self.db.user.set(nid, age=1.0)
        self.assertEqual(self.db.user.get(nid, 'age'), 1)
        self.db.user.set(nid, age=0)
        self.assertEqual(self.db.user.get(nid, 'age'), 0)

        nid = self.db.user.create(username='bar', age=0)
        self.assertEqual(self.db.user.get(nid, 'age'), 0)

    def testNumberUnset(self):
        nid = self.db.user.create(username='foo', age=1)
        self.db.user.set(nid, age=None)
        self.assertEqual(self.db.user.get(nid, "age"), None)

    # Long number
    def testDoubleChange(self):
        lnl = 100.12345678
        ln  = 100.123456789
        lng = 100.12345679
        nid = self.db.user.create(username='foo', longnumber=ln)
        self.assertEqual(self.db.user.get(nid, 'longnumber') < lng, True)
        self.assertEqual(self.db.user.get(nid, 'longnumber') > lnl, True)
        lnl = 1.0012345678e55
        ln  = 1.00123456789e55
        lng = 1.0012345679e55
        self.db.user.set(nid, longnumber=ln)
        self.assertEqual(self.db.user.get(nid, 'longnumber') < lng, True)
        self.assertEqual(self.db.user.get(nid, 'longnumber') > lnl, True)
        self.db.user.set(nid, longnumber=-1)
        self.assertEqual(self.db.user.get(nid, 'longnumber'), -1)
        self.db.user.set(nid, longnumber=0)
        self.assertEqual(self.db.user.get(nid, 'longnumber'), 0)

        nid = self.db.user.create(username='bar', longnumber=0)
        self.assertEqual(self.db.user.get(nid, 'longnumber'), 0)

    def testDoubleUnset(self):
        nid = self.db.user.create(username='foo', longnumber=1.2345)
        self.db.user.set(nid, longnumber=None)
        self.assertEqual(self.db.user.get(nid, "longnumber"), None)


    # Integer
    def testIntegerChange(self):
        nid = self.db.user.create(username='foo', rating=100)
        self.assertEqual(100, self.db.user.get(nid, 'rating'))
        self.db.user.set(nid, rating=300)
        self.assertNotEqual(self.db.user.get(nid, 'rating'), 100)
        self.db.user.set(nid, rating=-1)
        self.assertEqual(self.db.user.get(nid, 'rating'), -1)
        self.db.user.set(nid, rating=0)
        self.assertEqual(self.db.user.get(nid, 'rating'), 0)

        nid = self.db.user.create(username='bar', rating=0)
        self.assertEqual(self.db.user.get(nid, 'rating'), 0)

    def testIntegerUnset(self):
        nid = self.db.user.create(username='foo', rating=1)
        self.db.user.set(nid, rating=None)
        self.assertEqual(self.db.user.get(nid, "rating"), None)

    # Password
    def testPasswordChange(self):
        x = password.Password('x')
        userid = self.db.user.create(username='foo', password=x)
        self.assertEqual(x, self.db.user.get(userid, 'password'))
        self.assertEqual(self.db.user.get(userid, 'password'), 'x')
        y = password.Password('y')
        self.db.user.set(userid, password=y)
        self.assertEqual(self.db.user.get(userid, 'password'), 'y')
        self.assertRaises(TypeError, self.db.user.create, userid,
            username='bar', password='x')
        self.assertRaises(TypeError, self.db.user.set, userid, password='x')

    def testPasswordUnset(self):
        x = password.Password('x')
        nid = self.db.user.create(username='foo', password=x)
        self.db.user.set(nid, assignable=None)
        self.assertEqual(self.db.user.get(nid, "assignable"), None)

    # key value
    def testKeyValue(self):
        self.assertRaises(ValueError, self.db.user.create)

        newid = self.db.user.create(username="spam")
        self.assertEqual(self.db.user.lookup('spam'), newid)
        self.db.commit()
        self.assertEqual(self.db.user.lookup('spam'), newid)
        self.db.user.retire(newid)
        self.assertRaises(KeyError, self.db.user.lookup, 'spam')

        # use the key again now that the old is retired
        newid2 = self.db.user.create(username="spam")
        self.assertNotEqual(newid, newid2)
        # try to restore old node. this shouldn't succeed!
        self.assertRaises(KeyError, self.db.user.restore, newid)

        self.assertRaises(TypeError, self.db.issue.lookup, 'fubar')

    # label property
    def testLabelProp(self):
        # key prop
        self.assertEqual(self.db.status.labelprop(), 'name')
        self.assertEqual(self.db.user.labelprop(), 'username')
        # title
        self.assertEqual(self.db.issue.labelprop(), 'title')
        # name
        self.assertEqual(self.db.file.labelprop(), 'name')
        # id
        self.assertEqual(self.db.stuff.labelprop(default_to_id=1), 'id')

    # retirement
    def testRetire(self):
        self.db.issue.create(title="spam", status='1')
        b = self.db.status.get('1', 'name')
        a = self.db.status.list()
        nodeids = self.db.status.getnodeids()
        self.db.status.retire('1')
        others = nodeids[:]
        others.remove('1')

        self.assertEqual(set(self.db.status.getnodeids()),
            set(nodeids))
        self.assertEqual(set(self.db.status.getnodeids(retired=True)),
            set(['1']))
        self.assertEqual(set(self.db.status.getnodeids(retired=False)),
            set(others))

        self.assertTrue(self.db.status.is_retired('1'))

        # make sure the list is different
        self.assertNotEqual(a, self.db.status.list())

        # can still access the node if necessary
        self.assertEqual(self.db.status.get('1', 'name'), b)
        self.assertRaises(IndexError, self.db.status.set, '1', name='hello')
        self.db.commit()
        self.assertTrue(self.db.status.is_retired('1'))
        self.assertEqual(self.db.status.get('1', 'name'), b)
        self.assertNotEqual(a, self.db.status.list())

        # try to restore retired node
        self.db.status.restore('1')

        self.assertTrue(not self.db.status.is_retired('1'))

    def testCacheCreateSet(self):
        self.db.issue.create(title="spam", status='1')
        a = self.db.issue.get('1', 'title')
        self.assertEqual(a, 'spam')
        self.db.issue.set('1', title='ham')
        b = self.db.issue.get('1', 'title')
        self.assertEqual(b, 'ham')

    def testSerialisation(self):
        nid = self.db.issue.create(title="spam", status='1',
            deadline=date.Date(), foo=date.Interval('-1d'))
        self.db.commit()
        assert isinstance(self.db.issue.get(nid, 'deadline'), date.Date)
        assert isinstance(self.db.issue.get(nid, 'foo'), date.Interval)
        uid = self.db.user.create(username="fozzy",
            password=password.Password('t. bear'))
        self.db.commit()
        assert isinstance(self.db.user.get(uid, 'password'), password.Password)

    def testTransactions(self):
        # remember the number of items we started
        num_issues = len(self.db.issue.list())
        num_files = self.db.numfiles()
        self.db.issue.create(title="don't commit me!", status='1')
        self.assertNotEqual(num_issues, len(self.db.issue.list()))
        self.db.rollback()
        self.assertEqual(num_issues, len(self.db.issue.list()))
        self.db.issue.create(title="please commit me!", status='1')
        self.assertNotEqual(num_issues, len(self.db.issue.list()))
        self.db.commit()
        self.assertNotEqual(num_issues, len(self.db.issue.list()))
        self.db.rollback()
        self.assertNotEqual(num_issues, len(self.db.issue.list()))
        self.db.file.create(name="test", type="text/plain", content="hi")
        self.db.rollback()
        self.assertEqual(num_files, self.db.numfiles())
        for i in range(10):
            self.db.file.create(name="test", type="text/plain",
                    content="hi %d"%(i))
            self.db.commit()
        num_files2 = self.db.numfiles()
        self.assertNotEqual(num_files, num_files2)
        self.db.file.create(name="test", type="text/plain", content="hi")
        self.db.rollback()
        self.assertNotEqual(num_files, self.db.numfiles())
        self.assertEqual(num_files2, self.db.numfiles())

        # rollback / cache interaction
        name1 = self.db.user.get('1', 'username')
        self.db.user.set('1', username = name1+name1)
        # get the prop so the info's forced into the cache (if there is one)
        self.db.user.get('1', 'username')
        self.db.rollback()
        name2 = self.db.user.get('1', 'username')
        self.assertEqual(name1, name2)

    def testDestroyBlob(self):
        # destroy an uncommitted blob
        f1 = self.db.file.create(content='hello', type="text/plain")
        self.db.commit()
        fn = self.db.filename('file', f1)
        self.db.file.destroy(f1)
        self.db.commit()
        self.assertEqual(os.path.exists(fn), False)

    def testDestroyNoJournalling(self):
        self.innerTestDestroy(klass=self.db.session)

    def testDestroyJournalling(self):
        self.innerTestDestroy(klass=self.db.issue)

    def innerTestDestroy(self, klass):
        newid = klass.create(title='Mr Friendly')
        n = len(klass.list())
        self.assertEqual(klass.get(newid, 'title'), 'Mr Friendly')
        count = klass.count()
        klass.destroy(newid)
        self.assertNotEqual(count, klass.count())
        self.assertRaises(IndexError, klass.get, newid, 'title')
        self.assertNotEqual(len(klass.list()), n)
        if klass.do_journal:
            self.assertRaises(IndexError, klass.history, newid)

        # now with a commit
        newid = klass.create(title='Mr Friendly')
        n = len(klass.list())
        self.assertEqual(klass.get(newid, 'title'), 'Mr Friendly')
        self.db.commit()
        count = klass.count()
        klass.destroy(newid)
        self.assertNotEqual(count, klass.count())
        self.assertRaises(IndexError, klass.get, newid, 'title')
        self.db.commit()
        self.assertRaises(IndexError, klass.get, newid, 'title')
        self.assertNotEqual(len(klass.list()), n)
        if klass.do_journal:
            self.assertRaises(IndexError, klass.history, newid)

        # now with a rollback
        newid = klass.create(title='Mr Friendly')
        n = len(klass.list())
        self.assertEqual(klass.get(newid, 'title'), 'Mr Friendly')
        self.db.commit()
        count = klass.count()
        klass.destroy(newid)
        self.assertNotEqual(len(klass.list()), n)
        self.assertRaises(IndexError, klass.get, newid, 'title')
        self.db.rollback()
        self.assertEqual(count, klass.count())
        self.assertEqual(klass.get(newid, 'title'), 'Mr Friendly')
        self.assertEqual(len(klass.list()), n)
        if klass.do_journal:
            self.assertNotEqual(klass.history(newid), [])

    def testExceptions(self):
        # this tests the exceptions that should be raised
        ar = self.assertRaises

        ar(KeyError, self.db.getclass, 'fubar')

        #
        # class create
        #
        # string property
        ar(TypeError, self.db.status.create, name=1)
        # id, creation, creator and activity properties are reserved
        ar(KeyError, self.db.status.create, id=1)
        ar(KeyError, self.db.status.create, creation=1)
        ar(KeyError, self.db.status.create, creator=1)
        ar(KeyError, self.db.status.create, activity=1)
        ar(KeyError, self.db.status.create, actor=1)
        # invalid property name
        ar(KeyError, self.db.status.create, foo='foo')
        # key name clash
        ar(ValueError, self.db.status.create, name='unread')
        # invalid link index
        ar(IndexError, self.db.issue.create, title='foo', status='bar')
        # invalid link value
        ar(ValueError, self.db.issue.create, title='foo', status=1)
        # invalid multilink type
        ar(TypeError, self.db.issue.create, title='foo', status='1',
            nosy='hello')
        # invalid multilink index type
        ar(ValueError, self.db.issue.create, title='foo', status='1',
            nosy=[1])
        # invalid multilink index
        ar(IndexError, self.db.issue.create, title='foo', status='1',
            nosy=['10'])

        #
        # key property
        #
        # key must be a String
        ar(TypeError, self.db.file.setkey, 'fooz')
        # key must exist
        ar(KeyError, self.db.file.setkey, 'fubar')

        #
        # class get
        #
        # invalid node id
        ar(IndexError, self.db.issue.get, '99', 'title')
        # invalid property name
        ar(KeyError, self.db.status.get, '2', 'foo')

        #
        # class set
        #
        # invalid node id
        ar(IndexError, self.db.issue.set, '99', title='foo')
        # invalid property name
        ar(KeyError, self.db.status.set, '1', foo='foo')
        # string property
        ar(TypeError, self.db.status.set, '1', name=1)
        # key name clash
        ar(ValueError, self.db.status.set, '2', name='unread')
        # set up a valid issue for me to work on
        id = self.db.issue.create(title="spam", status='1')
        # invalid link index
        ar(IndexError, self.db.issue.set, id, title='foo', status='bar')
        # invalid link value
        ar(ValueError, self.db.issue.set, id, title='foo', status=1)
        # invalid multilink type
        ar(TypeError, self.db.issue.set, id, title='foo', status='1',
            nosy='hello')
        # invalid multilink index type
        ar(ValueError, self.db.issue.set, id, title='foo', status='1',
            nosy=[1])
        # invalid multilink index
        ar(IndexError, self.db.issue.set, id, title='foo', status='1',
            nosy=['10'])
        # NOTE: the following increment the username to avoid problems
        # within metakit's backend (it creates the node, and then sets the
        # info, so the create (and by a fluke the username set) go through
        # before the age/assignable/etc. set, which raises the exception)
        # invalid number value
        ar(TypeError, self.db.user.create, username='foo', age='a')
        # invalid boolean value
        ar(TypeError, self.db.user.create, username='foo2', assignable='true')
        nid = self.db.user.create(username='foo3')
        # invalid number value
        ar(TypeError, self.db.user.set, nid, age='a')
        # invalid boolean value
        ar(TypeError, self.db.user.set, nid, assignable='true')

    def testAuditors(self):
        class test:
            called = False
            def call(self, *args): self.called = True
        create = test()

        self.db.user.audit('create', create.call)
        self.db.user.create(username="mary")
        self.assertEqual(create.called, True)

        set = test()
        self.db.user.audit('set', set.call)
        self.db.user.set('1', username="joe")
        self.assertEqual(set.called, True)

        retire = test()
        self.db.user.audit('retire', retire.call)
        self.db.user.retire('1')
        self.assertEqual(retire.called, True)

    def testAuditorTwo(self):
        class test:
            n = 0
            def a(self, *args): self.call_a = self.n; self.n += 1
            def b(self, *args): self.call_b = self.n; self.n += 1
            def c(self, *args): self.call_c = self.n; self.n += 1
        test = test()
        self.db.user.audit('create', test.b, 1)
        self.db.user.audit('create', test.a, 1)
        self.db.user.audit('create', test.c, 2)
        self.db.user.create(username="mary")
        self.assertEqual(test.call_a, 0)
        self.assertEqual(test.call_b, 1)
        self.assertEqual(test.call_c, 2)

    def testDefault_Value(self):
        new_issue=self.db.issue.create(title="title", deadline=date.Date('2016-6-30.22:39'))

        # John Rouillard claims this should return the default value of 1 week for foo,
        # but the hyperdb doesn't assign the default value for missing properties in the
        # db on creation.
        result=self.db.issue.get(new_issue, 'foo')
        # When the defaultis automatically set by the hyperdb, change this to
        # match the Interval test below.
        self.assertEqual(result, None)

        # but verify that the default value is retreivable
        result=self.db.issue.properties['foo'].get_default_value()
        self.assertEqual(result, date.Interval('-7d'))

    def testQuietProperty(self):
        # make sure that the quiet properties: "assignable" and "age" are not
        # returned as part of the proplist
        new_user=self.db.user.create(username="pete", age=10, assignable=False)
        new_issue=self.db.issue.create(title="title", deadline=date.Date('2016-6-30.22:39'))
        # change all quiet params. Verify they aren't returned in object.
        # between this and the issue class every type represented in hyperdb
        # should be initalized with a quiet parameter.
        result=self.db.user.set(new_user, username="new", age=20, supervisor='3', assignable=True,
                                password=password.Password("3456"), rating=4, realname="newname")
        self.assertEqual(result, {'supervisor': '3', 'username': "new"})
        result=self.db.user.get(new_user, 'age')
        self.assertEqual(result, 20)

        # change all quiet params. Verify they aren't returned in object.
        result=self.db.issue.set(new_issue, title="title2", deadline=date.Date('2016-7-13.22:39'),
                                 assignedto="2", nosy=["3", "2"])
        self.assertEqual(result, {'title': 'title2'})

        # also test that we can make a property noisy
        self.db.user.properties['age'].quiet=False
        result=self.db.user.set(new_user, username="old", age=30, supervisor='2', assignable=False)
        self.assertEqual(result, {'age': 30, 'supervisor': '2', 'username': "old"})
        self.db.user.properties['age'].quiet=True

    def testQuietChangenote(self):
        # create user 3 for later use
        self.db.user.create(username="pete", age=10, assignable=False)

        new_issue=self.db.issue.create(title="title", deadline=date.Date('2016-6-30.22:39'))

        # change all quiet params. Verify they aren't returned in CreateNote.
        result=self.db.issue.set(new_issue, title="title2", deadline=date.Date('2016-6-30.22:39'),
                                 assignedto="2", nosy=["3", "2"])
        result=self.db.issue.generateCreateNote(new_issue)
        self.assertEqual(result, '\n----------\ntitle: title2')

        # also test that we can make a property noisy
        self.db.issue.properties['nosy'].quiet=False
        self.db.issue.properties['deadline'].quiet=False
        result=self.db.issue.set(new_issue, title="title2", deadline=date.Date('2016-7-13.22:39'),
                                 assignedto="2", nosy=["1", "2"])
        result=self.db.issue.generateCreateNote(new_issue)
        self.assertEqual(result, '\n----------\ndeadline: 2016-07-13.22:39:00\nnosy: admin, fred\ntitle: title2')
        self.db.issue.properties['nosy'].quiet=True
        self.db.issue.properties['deadline'].quiet=True

    def testViewPremJournal(self):
        pass

    def testQuietJournal(self):
        ## This is an example of how to enable logging module
        ## and report the results. It uses testfixtures
        ## that can be installed via pip.
        ## Uncomment below 2 lines:
        #import logging
        #from testfixtures import LogCapture
        ## then run every call to roundup functions with:
        #with LogCapture('roundup.hyperdb', level=logging.DEBUG) as l:
        #    result=self.db.user.history('2')
        #print l
        ## change 'roundup.hyperdb' to the logging name you want to capture.
        ## print l just prints the output. Run using:
        ## python -m pytest --capture=no -k testQuietJournal test/test_anydbm.py

        # FIXME There should be a test via
        # template.py::_HTMLItem::history() and verify the output.
        # not sure how to get there from here. -- rouilj

        # The Class::history() method now does filtering of quiet
        # props. Make sure that the quiet properties: "assignable"
        # and "age" are not returned as part of the journal
        new_user=self.db.user.create(username="pete", age=10, assignable=False)
        new_issue=self.db.issue.create(title="title", deadline=date.Date('2016-6-30.22:39'))

        # change all quiet params. Verify they aren't returned in journal.
        # between this and the issue class every type represented in hyperdb
        # should be initalized with a quiet parameter.
        result=self.db.user.set(new_user, username="new", age=20,
                                supervisor='1', assignable=True,
                                password=password.Password("3456"),
                                rating=4, realname="newname")
        result=self.db.user.history(new_user, skipquiet=False)
        '''
        [('3', <Date 2017-04-14.02:12:20.922>, '1', 'create', {}),
         ('3', <Date 2017-04-14.02:12:20.922>, '1', 'set',
           {'username': 'pete', 'assignable': False,
            'supervisor': None, 'realname': None, 'rating': None,
            'age': 10, 'password': None})]
        '''
        expected = {'username': 'pete', 'assignable': False,
            'supervisor': None, 'realname': None, 'rating': None,
            'age': 10, 'password': None}

        result.sort()
        (id, tx_date, user, action, args) = result[-1]
        # check piecewise ignoring date of transaction
        self.assertEqual('3', id)
        self.assertEqual('1', user)
        self.assertEqual('set', action)
        self.assertEqual(expected, args)

        # change all quiet params on issue.
        result=self.db.issue.set(new_issue, title="title2",
                                 deadline=date.Date('2016-07-30.22:39'),
                                 assignedto="2", nosy=["3", "2"])
        result=self.db.issue.generateCreateNote(new_issue)
        self.assertEqual(result, '\n----------\ntitle: title2')

        # check history including quiet properties
        result=self.db.issue.history(new_issue, skipquiet=False)
        print(result)
        ''' output should be like:
             [ ... ('1', <Date 2017-04-14.01:41:08.466>, '1', 'set',
                 {'assignedto': None, 'nosy': (('+', ['3', '2']),),
                     'deadline': <Date 2016-06-30.22:39:00.000>,
                     'title': 'title'})
        '''
        expected = {'assignedto': None,
                    'nosy': (('+', ['3', '2']),),
                    'deadline': date.Date('2016-06-30.22:39'),
                    'title': 'title'}

        result.sort()
        print("history include quiet props", result[-1])
        (id, tx_date, user, action, args) = result[-1]
        # check piecewise ignoring date of transaction
        self.assertEqual('1', id)
        self.assertEqual('1', user)
        self.assertEqual('set', action)
        self.assertEqual(expected, args)

        # check history removing quiet properties
        result=self.db.issue.history(new_issue)
        ''' output should be like:
             [ ... ('1', <Date 2017-04-14.01:41:08.466>, '1', 'set',
                 {'title': 'title'})
        '''
        expected = {'title': 'title'}

        result.sort()
        print("history remove quiet props", result[-1])
        (id, tx_date, user, action, args) = result[-1]
        # check piecewise
        self.assertEqual('1', id)
        self.assertEqual('1', user)
        self.assertEqual('set', action)
        self.assertEqual(expected, args)

        # also test that we can make a property noisy
        self.db.issue.properties['nosy'].quiet=False
        self.db.issue.properties['deadline'].quiet=False

        # FIXME: mysql use should be fixed or
        # a different way of checking this should be done.
        # this sleep is a hack.
        # mysql transation timestamps are in whole
        # seconds. To get the history to sort in proper
        # order by using timestamps we have to sleep 2 seconds
        # here tomake sure the timestamp between this transaction
        # and the last transaction is at least 1 second apart.
        import time; time.sleep(2)
        result=self.db.issue.set(new_issue, title="title2",
                                 deadline=date.Date('2016-7-13.22:39'),
                                 assignedto="2", nosy=["1", "2"])
        result=self.db.issue.generateCreateNote(new_issue)
        self.assertEqual(result, '\n----------\ndeadline: 2016-07-13.22:39:00\nnosy: admin, fred\ntitle: title2')


        # check history removing the current quiet properties
        result=self.db.issue.history(new_issue)
        expected = {'nosy': (('+', ['1']), ('-', ['3'])),
                    'deadline': date.Date("2016-07-30.22:39:00.000")}

        result.sort()
        print("result unquiet", result)
        (id, tx_date, user, action, args) = result[-1]
        # check piecewise
        self.assertEqual('1', id)
        self.assertEqual('1', user)
        self.assertEqual('set', action)
        self.assertEqual(expected, args)

        result=self.db.user.history('2')
        result.sort()

        # result should look like:
        #  [('2', <Date 2017-08-29.01:42:40.227>, '1', 'create', {}),
        #   ('2', <Date 2017-08-29.01:42:44.283>, '1', 'link',
        #      ('issue', '1', 'nosy')) ]

        expected2 = ('issue', '1', 'nosy')

        (id, tx_date, user, action, args) = result[-1]

        self.assertEqual(len(result),2)

        self.assertEqual('2', id)
        self.assertEqual('1', user)
        self.assertEqual('link', action)
        self.assertEqual(expected2, args)

        # reset quiet props
        self.db.issue.properties['nosy'].quiet=True
        self.db.issue.properties['deadline'].quiet=True

        # Change the role for the new_user.
        # If journal is retrieved by admin this adds the role
        # change as the last element. If retreived by non-admin
        # it should not be returned because the user has no
        # View permissons on role.
        # FIXME delay by two seconds due to mysql missing
        # fractional seconds. See sleep above for details
        time.sleep(2)
        result=self.db.user.set(new_user, roles="foo, bar")

        # Verify last journal entry as admin is a role change
        # from None
        result=self.db.user.history(new_user, skipquiet=False)
        result.sort()
        ''' result should end like:
          [ ...
          ('3', <Date 2017-04-15.02:06:11.482>, '1', 'set',
                {'username': 'pete', 'assignable': False,
                 'supervisor': None, 'realname': None,
                  'rating': None, 'age': 10, 'password': None}),
          ('3', <Date 2017-04-15.02:06:11.482>, '1', 'link',
                ('issue', '1', 'nosy')),
          ('3', <Date 2017-04-15.02:06:11.482>, '1', 'unlink',
                ('issue', '1', 'nosy')),
          ('3', <Date 2017-04-15.02:06:11.482>, '1', 'set',
             {'roles': None})]
        '''
        (id, tx_date, user, action, args) = result[-1]
        expected = {'roles': None }

        self.assertEqual('3', id)
        self.assertEqual('1', user)
        self.assertEqual('set', action)
        self.assertEqual(expected, args)

        # set an existing user's role to User so it can
        # view some props of the user class (search backwards
        # for QuietJournal to see the properties, they should be:
        # 'username', 'supervisor', 'assignable' i.e. age is not
        # one of them.
        id = self.db.user.lookup("fred")
        # FIXME mysql timestamp issue see sleeps above
        time.sleep(2)
        result=self.db.user.set(id, roles="User")
        # make the user fred current.
        self.db.setCurrentUser('fred')
        self.assertEqual(self.db.getuid(), id)

        # check history as the user fred
        #   include quiet properties
        #   but require View perms
        result=self.db.user.history(new_user, skipquiet=False)
        result.sort()
        ''' result should look like
        [('3', <Date 2017-04-15.01:43:26.911>, '1', 'create', {}),
        ('3', <Date 2017-04-15.01:43:26.911>, '1', 'set',
            {'username': 'pete', 'assignable': False,
              'supervisor': None, 'age': 10})]
        '''
        # analyze last item
        (id, tx_date, user, action, args) = result[-1]
        expected= {'username': 'pete', 'assignable': False,
                   'supervisor': None}

        self.assertEqual('3', id)
        self.assertEqual('1', user)
        self.assertEqual('set', action)
        self.assertEqual(expected, args)

        # reset the user to admin
        self.db.setCurrentUser('admin')
        self.assertEqual(self.db.getuid(), '1') # admin is always 1

    def testJournals(self):
        muid = self.db.user.create(username="mary")
        self.db.user.create(username="pete")
        self.db.issue.create(title="spam", status='1')
        self.db.commit()

        # journal entry for issue create
        journal = self.db.getjournal('issue', '1')
        self.assertEqual(1, len(journal))
        (nodeid, date_stamp, journaltag, action, params) = journal[0]
        self.assertEqual(nodeid, '1')
        self.assertEqual(journaltag, self.db.user.lookup('admin'))
        self.assertEqual(action, 'create')
        keys = sorted(params.keys())
        self.assertEqual(keys, [])

        # journal entry for link
        journal = self.db.getjournal('user', '1')
        self.assertEqual(1, len(journal))
        self.db.issue.set('1', assignedto='1')
        self.db.commit()
        journal = self.db.getjournal('user', '1')
        self.assertEqual(2, len(journal))
        (nodeid, date_stamp, journaltag, action, params) = journal[1]
        self.assertEqual('1', nodeid)
        self.assertEqual('1', journaltag)
        self.assertEqual('link', action)
        self.assertEqual(('issue', '1', 'assignedto'), params)

        # wait a bit to keep proper order of journal entries
        time.sleep(0.01)
        # journal entry for unlink
        self.db.setCurrentUser('mary')
        self.db.issue.set('1', assignedto='2')
        self.db.commit()
        journal = self.db.getjournal('user', '1')
        self.assertEqual(3, len(journal))
        (nodeid, date_stamp, journaltag, action, params) = journal[2]
        self.assertEqual('1', nodeid)
        self.assertEqual(muid, journaltag)
        self.assertEqual('unlink', action)
        self.assertEqual(('issue', '1', 'assignedto'), params)

        # test disabling journalling
        # ... get the last entry
        jlen = len(self.db.getjournal('user', '1'))
        self.db.issue.disableJournalling()
        self.db.issue.set('1', title='hello world')
        self.db.commit()
        # see if the change was journalled when it shouldn't have been
        self.assertEqual(jlen,  len(self.db.getjournal('user', '1')))
        jlen = len(self.db.getjournal('issue', '1'))
        self.db.issue.enableJournalling()
        self.db.issue.set('1', title='hello world 2')
        self.db.commit()
        # see if the change was journalled
        self.assertNotEqual(jlen,  len(self.db.getjournal('issue', '1')))

    def testJournalNonexistingProperty(self):
        # Test for non-existing properties, link/unlink events to
        # non-existing classes and link/unlink events to non-existing
        # properties in a class: These all may be the result of a schema
        # change and should not lead to a traceback.
        self.db.user.create(username="mary", roles="User")
        id = self.db.issue.create(title="spam", status='1')
        # FIXME delay by two seconds due to mysql missing
        # fractional seconds. This keeps the journal order correct.
        time.sleep(2)
        self.db.issue.set(id, title='green eggs')
        time.sleep(2)
        self.db.commit()
        journal = self.db.getjournal('issue', id)
        now     = date.Date('.')
        sec     = date.Interval('0:00:01')
        sec2    = date.Interval('0:00:02')
        jp0 = dict(title = 'spam')
        # Non-existing property changed
        jp1 = dict(nonexisting = None)
        journal.append ((id, now, '1', 'set', jp1))
        # Link from user-class to non-existing property
        jp2 = ('user', '1', 'xyzzy')
        journal.append ((id, now+sec, '1', 'link', jp2))
        # Link from non-existing class
        jp3 = ('frobozz', '1', 'xyzzy')
        journal.append ((id, now+sec2, '1', 'link', jp3))
        self.db.setjournal('issue', id, journal)
        self.db.commit()
        result=self.db.issue.history(id)
        result.sort()
        # anydbm drops unknown properties during serialisation
        if self.db.dbtype == 'anydbm':
            self.assertEqual(len(result), 4)
            self.assertEqual(result [1][4], jp0)
            self.assertEqual(result [2][4], jp2)
            self.assertEqual(result [3][4], jp3)
        else:
            self.assertEqual(len(result), 5)
            self.assertEqual(result [1][4], jp0)
            print(result) # following test fails sometimes under sqlite
                          # in travis. Looks like an ordering issue
                          # in python 3.5. Print result to debug.
            self.assertEqual(result [2][4], jp1)
            self.assertEqual(result [3][4], jp2)
            self.assertEqual(result [4][4], jp3)
        self.db.close()
        # Verify that normal user doesn't see obsolete props/classes
        self.open_database('mary')
        setupSchema(self.db, 0, self.module)
        # allow mary to see issue fields like title
        self.db.security.addPermissionToRole('User', 'View', 'issue')
        result=self.db.issue.history(id)
        self.assertEqual(len(result), 2)
        self.assertEqual(result [1][4], jp0)

    def testJournalPreCommit(self):
        id = self.db.user.create(username="mary")
        self.assertEqual(len(self.db.getjournal('user', id)), 1)
        self.db.commit()

    def testPack(self):
        id = self.db.issue.create(title="spam", status='1')
        self.db.commit()
        time.sleep(1)
        self.db.issue.set(id, status='2')
        self.db.commit()

        # sleep for at least a second, then get a date to pack at
        time.sleep(1)
        pack_before = date.Date('.')

        # wait another second and add one more entry
        time.sleep(1)
        self.db.issue.set(id, status='3')
        self.db.commit()
        jlen = len(self.db.getjournal('issue', id))

        # pack
        self.db.pack(pack_before)

        # we should have the create and last set entries now
        self.assertEqual(jlen-1, len(self.db.getjournal('issue', id)))

    def testIndexerSearching(self):
        f1 = self.db.file.create(content='hello', type="text/plain")
        # content='world' has the wrong content-type and won't be indexed
        f2 = self.db.file.create(content='world', type="text/frozz",
            comment='blah blah')
        i1 = self.db.issue.create(files=[f1, f2], title="flebble plop")
        i2 = self.db.issue.create(title="flebble the frooz")
        self.db.commit()
        self.assertEqual(self.db.indexer.search([], self.db.issue), {})
        self.assertEqual(self.db.indexer.search(['hello'], self.db.issue),
            {i1: {'files': [f1]}})
        # content='world' has the wrong content-type and shouldn't be indexed
        self.assertEqual(self.db.indexer.search(['world'], self.db.issue), {})
        self.assertEqual(self.db.indexer.search(['frooz'], self.db.issue),
            {i2: {}})
        self.assertEqual(self.db.indexer.search(['flebble'], self.db.issue),
            {i1: {}, i2: {}})

        # test AND'ing of search terms
        self.assertEqual(self.db.indexer.search(['frooz', 'flebble'],
            self.db.issue), {i2: {}})

        # unindexed stopword
        self.assertEqual(self.db.indexer.search(['the'], self.db.issue), {})

    def testIndexerSearchingLink(self):
        m1 = self.db.msg.create(content="one two")
        i1 = self.db.issue.create(messages=[m1])
        m2 = self.db.msg.create(content="two three")
        i2 = self.db.issue.create(feedback=m2)
        self.db.commit()
        self.assertEqual(self.db.indexer.search(['two'], self.db.issue),
            {i1: {'messages': [m1]}, i2: {'feedback': [m2]}})

    def testIndexerSearchMulti(self):
        m1 = self.db.msg.create(content="one two")
        m2 = self.db.msg.create(content="two three")
        i1 = self.db.issue.create(messages=[m1])
        i2 = self.db.issue.create(spam=[m2])
        self.db.commit()
        self.assertEqual(self.db.indexer.search([], self.db.issue), {})
        self.assertEqual(self.db.indexer.search(['one'], self.db.issue),
            {i1: {'messages': [m1]}})
        self.assertEqual(self.db.indexer.search(['two'], self.db.issue),
            {i1: {'messages': [m1]}, i2: {'spam': [m2]}})
        self.assertEqual(self.db.indexer.search(['three'], self.db.issue),
            {i2: {'spam': [m2]}})

    def testReindexingChange(self):
        search = self.db.indexer.search
        issue = self.db.issue
        i1 = issue.create(title="flebble plop")
        i2 = issue.create(title="flebble frooz")
        self.db.commit()
        self.assertEqual(search(['plop'], issue), {i1: {}})
        self.assertEqual(search(['flebble'], issue), {i1: {}, i2: {}})

        # change i1's title
        issue.set(i1, title="plop")
        self.db.commit()
        self.assertEqual(search(['plop'], issue), {i1: {}})
        self.assertEqual(search(['flebble'], issue), {i2: {}})

    def testReindexingClear(self):
        search = self.db.indexer.search
        issue = self.db.issue
        i1 = issue.create(title="flebble plop")
        i2 = issue.create(title="flebble frooz")
        self.db.commit()
        self.assertEqual(search(['plop'], issue), {i1: {}})
        self.assertEqual(search(['flebble'], issue), {i1: {}, i2: {}})

        # unset i1's title
        issue.set(i1, title="")
        self.db.commit()
        self.assertEqual(search(['plop'], issue), {})
        self.assertEqual(search(['flebble'], issue), {i2: {}})

    def testFileClassReindexing(self):
        f1 = self.db.file.create(content='hello')
        f2 = self.db.file.create(content='hello, world')
        i1 = self.db.issue.create(files=[f1, f2])
        self.db.commit()
        d = self.db.indexer.search(['hello'], self.db.issue)
        self.assertTrue(i1 in d)
        d[i1]['files'].sort()
        self.assertEqual(d, {i1: {'files': [f1, f2]}})
        self.assertEqual(self.db.indexer.search(['world'], self.db.issue),
            {i1: {'files': [f2]}})
        self.db.file.set(f1, content="world")
        self.db.commit()
        d = self.db.indexer.search(['world'], self.db.issue)
        d[i1]['files'].sort()
        self.assertEqual(d, {i1: {'files': [f1, f2]}})
        self.assertEqual(self.db.indexer.search(['hello'], self.db.issue),
            {i1: {'files': [f2]}})

    def testFileClassIndexingNoNoNo(self):
        f1 = self.db.file.create(content='hello')
        self.db.commit()
        self.assertEqual(self.db.indexer.search(['hello'], self.db.file),
            {'1': {}})

        f1 = self.db.file_nidx.create(content='hello')
        self.db.commit()
        self.assertEqual(self.db.indexer.search(['hello'], self.db.file_nidx),
            {})

    def testForcedReindexing(self):
        self.db.issue.create(title="flebble frooz")
        self.db.commit()
        self.assertEqual(self.db.indexer.search(['flebble'], self.db.issue),
            {'1': {}})
        self.db.indexer.quiet = 1
        self.db.indexer.force_reindex()
        self.db.post_init()
        self.db.indexer.quiet = 9
        self.assertEqual(self.db.indexer.search(['flebble'], self.db.issue),
            {'1': {}})

    def testIndexingPropertiesOnImport(self):
        # import an issue
        title = 'Bzzt'
        nodeid = self.db.issue.import_list(['title', 'messages', 'files',
            'spam', 'nosy', 'superseder', 'keywords', 'keywords2'],
            [repr(title), '[]', '[]', '[]', '[]', '[]', '[]', '[]'])
        self.db.commit()

        # Content of title attribute is indexed
        self.assertEqual(self.db.indexer.search([title], self.db.issue),
            {str(nodeid):{}})


    #
    # searching tests follow
    #
    def testFindIncorrectProperty(self):
        self.assertRaises(TypeError, self.db.issue.find, title='fubar')

    def _find_test_setup(self):
        self.db.file.create(content='')
        self.db.file.create(content='')
        self.db.user.create(username='')
        one = self.db.issue.create(status="1", nosy=['1'])
        two = self.db.issue.create(status="2", nosy=['2'], files=['1'],
            assignedto='2')
        three = self.db.issue.create(status="1", nosy=['1','2'])
        four = self.db.issue.create(status="3", assignedto='1',
            files=['1','2'])
        return one, two, three, four

    def testFindLink(self):
        one, two, three, four = self._find_test_setup()
        got = self.db.issue.find(status='1')
        got.sort()
        self.assertEqual(got, [one, three])
        got = self.db.issue.find(status={'1':1})
        got.sort()
        self.assertEqual(got, [one, three])

    def testFindProtectedLink(self):
        one, two, three, four = self._find_test_setup()
        got = self.db.issue.find(creator='1')
        got.sort()
        self.assertEqual(got, [one, two, three, four])

    def testFindRevLinkMultilink(self):
        ae, dummy = self.filteringSetupTransitiveSearch('user')
        ni = 'nosy_issues'
        self.db.issue.set('6', nosy=['3', '4', '5'])
        self.db.issue.set('7', nosy=['5'])
        # After this setup we have the following values for nosy:
        # issue  assignedto  nosy
        # 1:      6          4
        # 2:      6          5
        # 3:      7
        # 4:      8
        # 5:      9
        # 6:      10         3, 4, 5
        # 7:      10         5
        # 8:      10
        # assignedto links back from 'issues'
        # nosy links back from 'nosy_issues'
        self.assertEqual(self.db.user.find(issues={'1':1}), ['6'])
        self.assertEqual(self.db.user.find(issues={'8':1}), ['10'])
        self.assertEqual(self.db.user.find(issues={'2':1, '5':1}), ['6', '9'])
        self.assertEqual(self.db.user.find(nosy_issues={'8':1}), [])
        self.assertEqual(self.db.user.find(nosy_issues={'6':1}),
            ['3', '4', '5'])
        self.assertEqual(self.db.user.find(nosy_issues={'3':1, '5':1}), [])
        self.assertEqual(self.db.user.find(nosy_issues={'2':1, '6':1, '7':1}),
            ['3', '4', '5'])

    def testFindLinkFail(self):
        self._find_test_setup()
        self.assertEqual(self.db.issue.find(status='4'), [])
        self.assertEqual(self.db.issue.find(status={'4':1}), [])

    def testFindLinkUnset(self):
        one, two, three, four = self._find_test_setup()
        got = self.db.issue.find(assignedto=None)
        got.sort()
        self.assertEqual(got, [one, three])
        got = self.db.issue.find(assignedto={None:1})
        got.sort()
        self.assertEqual(got, [one, three])

    def testFindMultipleLink(self):
        one, two, three, four = self._find_test_setup()
        l = self.db.issue.find(status={'1':1, '3':1})
        l.sort()
        self.assertEqual(l, [one, three, four])
        l = self.db.issue.find(status=('1', '3'))
        l.sort()
        self.assertEqual(l, [one, three, four])
        l = self.db.issue.find(status=['1', '3'])
        l.sort()
        self.assertEqual(l, [one, three, four])
        l = self.db.issue.find(assignedto={None:1, '1':1})
        l.sort()
        self.assertEqual(l, [one, three, four])

    def testFindMultilink(self):
        one, two, three, four = self._find_test_setup()
        got = self.db.issue.find(nosy='2')
        got.sort()
        self.assertEqual(got, [two, three])
        got = self.db.issue.find(nosy={'2':1})
        got.sort()
        self.assertEqual(got, [two, three])
        got = self.db.issue.find(nosy={'2':1}, files={})
        got.sort()
        self.assertEqual(got, [two, three])

    def testFindMultiMultilink(self):
        one, two, three, four = self._find_test_setup()
        got = self.db.issue.find(nosy='2', files='1')
        got.sort()
        self.assertEqual(got, [two, three, four])
        got = self.db.issue.find(nosy={'2':1}, files={'1':1})
        got.sort()
        self.assertEqual(got, [two, three, four])

    def testFindMultilinkFail(self):
        self._find_test_setup()
        self.assertEqual(self.db.issue.find(nosy='3'), [])
        self.assertEqual(self.db.issue.find(nosy={'3':1}), [])

    def testFindMultilinkUnset(self):
        self._find_test_setup()
        self.assertEqual(self.db.issue.find(nosy={}), [])

    def testFindLinkAndMultilink(self):
        one, two, three, four = self._find_test_setup()
        got = self.db.issue.find(status='1', nosy='2')
        got.sort()
        self.assertEqual(got, [one, two, three])
        got = self.db.issue.find(status={'1':1}, nosy={'2':1})
        got.sort()
        self.assertEqual(got, [one, two, three])

    def testFindRetired(self):
        one, two, three, four = self._find_test_setup()
        self.assertEqual(len(self.db.issue.find(status='1')), 2)
        self.db.issue.retire(one)
        self.assertEqual(len(self.db.issue.find(status='1')), 1)

    def testStringFind(self):
        self.assertRaises(TypeError, self.db.issue.stringFind, status='1')

        ids = []
        ids.append(self.db.issue.create(title="spam"))
        self.db.issue.create(title="not spam")
        ids.append(self.db.issue.create(title="spam"))
        ids.sort()
        got = self.db.issue.stringFind(title='spam')
        got.sort()
        self.assertEqual(got, ids)
        self.assertEqual(self.db.issue.stringFind(title='fubar'), [])

        # test retiring a node
        self.db.issue.retire(ids[0])
        self.assertEqual(len(self.db.issue.stringFind(title='spam')), 1)

    def filteringSetup(self, classname='issue'):
        for user in (
                {'username': 'bleep', 'age': 1, 'assignable': True},
                {'username': 'blop', 'age': 1.5, 'assignable': True},
                {'username': 'blorp', 'age': 2, 'assignable': False}):
            self.db.user.create(**user)
        file_content = ''.join([chr(i) for i in range(255)])
        f = self.db.file.create(content=file_content)
        for issue in (
                {'title': 'issue one', 'status': '2', 'assignedto': '1',
                    'foo': date.Interval('1:10'), 'priority': '3',
                    'deadline': date.Date('2003-02-16.22:50')},
                {'title': 'issue two', 'status': '1', 'assignedto': '2',
                    'foo': date.Interval('1d'), 'priority': '3',
                    'deadline': date.Date('2003-01-01.00:00')},
                {'title': 'issue three', 'status': '1', 'priority': '2',
                    'nosy': ['1','2'], 'deadline': date.Date('2003-02-18')},
                {'title': 'non four', 'status': '3',
                    'foo': date.Interval('0:10'), 'priority': '2',
                    'nosy': ['1','2','3'], 'deadline': date.Date('2004-03-08'),
                    'files': [f]}):
            self.db.issue.create(**issue)
        self.db.commit()
        return self.iterSetup(classname)

    def testFilteringID(self):
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            ae(filt(None, {'id': '1'}, ('+','id'), (None,None)), ['1'])
            ae(filt(None, {'id': '2'}, ('+','id'), (None,None)), ['2'])
            ae(filt(None, {'id': '100'}, ('+','id'), (None,None)), [])

    def testFilteringBoolean(self):
        ae, iiter = self.filteringSetup('user')
        a = 'assignable'
        for filt in iiter():
            ae(filt(None, {a: '1'}, ('+','id'), (None,None)), ['3','4'])
            ae(filt(None, {a: '0'}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {a: ['1']}, ('+','id'), (None,None)), ['3','4'])
            ae(filt(None, {a: ['0']}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {a: ['0','1']}, ('+','id'), (None,None)),
                ['3','4','5'])
            ae(filt(None, {a: 'True'}, ('+','id'), (None,None)), ['3','4'])
            ae(filt(None, {a: 'False'}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {a: ['True']}, ('+','id'), (None,None)), ['3','4'])
            ae(filt(None, {a: ['False']}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {a: ['False','True']}, ('+','id'), (None,None)),
                ['3','4','5'])
            ae(filt(None, {a: True}, ('+','id'), (None,None)), ['3','4'])
            ae(filt(None, {a: False}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {a: 1}, ('+','id'), (None,None)), ['3','4'])
            ae(filt(None, {a: 0}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {a: [1]}, ('+','id'), (None,None)), ['3','4'])
            ae(filt(None, {a: [0]}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {a: [0,1]}, ('+','id'), (None,None)), ['3','4','5'])
            ae(filt(None, {a: [True]}, ('+','id'), (None,None)), ['3','4'])
            ae(filt(None, {a: [False]}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {a: [False,True]}, ('+','id'), (None,None)),
                ['3','4','5'])

    def testFilteringNumber(self):
        ae, iiter = self.filteringSetup('user')
        for filt in iiter():
            ae(filt(None, {'age': '1'}, ('+','id'), (None,None)), ['3'])
            ae(filt(None, {'age': '1.5'}, ('+','id'), (None,None)), ['4'])
            ae(filt(None, {'age': '2'}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {'age': ['1','2']}, ('+','id'), (None,None)),
                ['3','5'])
            ae(filt(None, {'age': 2}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {'age': [1,2]}, ('+','id'), (None,None)), ['3','5'])

    def testFilteringString(self):
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            ae(filt(None, {'title': ['one']}, ('+','id'), (None,None)), ['1'])
            ae(filt(None, {'title': ['issue one']}, ('+','id'), (None,None)),
                ['1'])
            ae(filt(None, {'title': ['issue', 'one']}, ('+','id'), (None,None)),
                ['1'])
            ae(filt(None, {'title': ['issue']}, ('+','id'), (None,None)),
                ['1','2','3'])
            ae(filt(None, {'title': ['one', 'two']}, ('+','id'), (None,None)),
                [])

    def testFilteringStringCase(self):
        """
        Similar to testFilteringString except the search parameters
        have different capitalization.
        """
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            ae(filt(None, {'title': ['One']}, ('+','id'), (None,None)), ['1'])
            ae(filt(None, {'title': ['Issue One']}, ('+','id'), (None,None)),
                ['1'])
            ae(filt(None, {'title': ['ISSUE', 'ONE']}, ('+','id'), (None,None)),
                ['1'])
            ae(filt(None, {'title': ['iSSUE']}, ('+','id'), (None,None)),
                ['1','2','3'])
            ae(filt(None, {'title': ['One', 'Two']}, ('+','id'), (None,None)),
                [])

    def testFilteringStringExactMatch(self):
        ae, iiter = self.filteringSetup()
        # Change title of issue2 to 'issue' so we can test substring
        # search vs exact search
        self.db.issue.set('2', title='issue')
        #self.db.commit()
        for filt in iiter():
            ae(filt(None, {}, exact_match_spec =
               {'title': ['one']}), [])
            ae(filt(None, {}, exact_match_spec =
               {'title': ['issue one']}), ['1'])
            ae(filt(None, {}, exact_match_spec =
               {'title': ['issue', 'one']}), [])
            ae(filt(None, {}, exact_match_spec =
               {'title': ['issue']}), ['2'])
            ae(filt(None, {}, exact_match_spec =
               {'title': ['one', 'two']}), [])
            ae(filt(None, {}, exact_match_spec =
               {'title': ['One']}), [])
            ae(filt(None, {}, exact_match_spec =
               {'title': ['Issue One']}), [])
            ae(filt(None, {}, exact_match_spec =
               {'title': ['ISSUE', 'ONE']}), [])
            ae(filt(None, {}, exact_match_spec =
               {'title': ['iSSUE']}), [])
            ae(filt(None, {}, exact_match_spec =
               {'title': ['One', 'Two']}), [])
            ae(filt(None, {}, exact_match_spec =
               {'title': ['non four']}), ['4'])
            # Both, filterspec and exact_match_spec on same prop
            ae(filt(None, {'title': 'iSSUE'}, exact_match_spec =
               {'title': ['issue']}), ['2'])

    def testFilteringSpecialChars(self):
        """ Special characters in SQL search are '%' and '_', some used
            to lead to a traceback.
        """
        ae, iiter = self.filteringSetup()
        self.db.issue.set('1', title="With % symbol")
        self.db.issue.set('2', title="With _ symbol")
        self.db.issue.set('3', title="With \\ symbol")
        self.db.issue.set('4', title="With ' symbol")
        d = dict (status = '1')
        for filt in iiter():
            ae(filt(None, dict(title='%'), ('+','id'), (None,None)), ['1'])
            ae(filt(None, dict(title='_'), ('+','id'), (None,None)), ['2'])
            ae(filt(None, dict(title='\\'), ('+','id'), (None,None)), ['3'])
            ae(filt(None, dict(title="'"), ('+','id'), (None,None)), ['4'])

    def testFilteringLink(self):
        ae, iiter = self.filteringSetup()
        a = 'assignedto'
        grp = (None, None)
        for filt in iiter():
            ae(filt(None, {'status': '1'}, ('+','id'), grp), ['2','3'])
            ae(filt(None, {'status': [], 'status.name': 'unread'}), [])
            ae(filt(None, {a: '-1'}, ('+','id'), grp), ['3','4'])
            ae(filt(None, {a: None}, ('+','id'), grp), ['3','4'])
            ae(filt(None, {a: [None]}, ('+','id'), grp), ['3','4'])
            ae(filt(None, {a: ['-1', None]}, ('+','id'), grp), ['3','4'])
            ae(filt(None, {a: ['1', None]}, ('+','id'), grp), ['1', '3','4'])

    def testFilteringLinkExpression(self):
        ae, iiter = self.filteringSetup()
        a = 'assignedto'
        for filt in iiter():
            ae(filt(None, {}, ('+',a)), ['3','4','1','2'])
            ae(filt(None, {a: '1'}, ('+',a)), ['1'])
            ae(filt(None, {a: '2'}, ('+',a)), ['2'])
            ae(filt(None, {a: '-1'}, ('+','status')), ['4','3'])
            ae(filt(None, {a: []}, ('+','id')), ['3','4'])
            ae(filt(None, {a: ['-1']}, ('+',a)), ['3','4'])
            ae(filt(None, {a: []}, ('+',a)), ['3','4'])
            ae(filt(None, {a: '-1'}, ('+',a)), ['3','4'])
            ae(filt(None, {a: ['1','-1']}), ['1','3','4'])
            ae(filt(None, {a: ['1','-1']}, ('+',a)), ['3','4','1'])
            ae(filt(None, {a: ['2','-1']}, ('+',a)), ['3','4','2'])
            ae(filt(None, {a: ['1','-2']}), ['2','3','4'])
            ae(filt(None, {a: ['1','-2']}, ('+',a)), ['3','4','2'])
            ae(filt(None, {a: ['-1','-2']}, ('+',a)), ['1','2'])
            ae(filt(None, {a: ['1','2','-3']}, ('+',a)), [])
            ae(filt(None, {a: ['1','2','-4']}, ('+',a)), ['1','2'])
            ae(filt(None, {a: ['1','-2','2','-2','-3']}, ('+',a)), ['3','4'])
            ae(filt(None, {a: ['1','-2','2','-2','-4']}, ('+',a)),
                ['3','4','1','2'])

    def testFilteringRevLink(self):
        ae, iiter = self.filteringSetupTransitiveSearch('user')
        # We have
        # issue assignedto
        # 1:    6
        # 2:    6
        # 3:    7
        # 4:    8
        # 5:    9
        # 6:    10
        # 7:    10
        # 8:    10
        for filt in iiter():
            ae(filt(None, {'issues': ['3', '4']}), ['7', '8'])
            ae(filt(None, {'issues': ['1', '4', '8']}), ['6', '8', '10'])
            ae(filt(None, {'issues.title': ['ts2']}), ['6'])
            ae(filt(None, {'issues': ['-1']}), ['1', '2', '3', '4', '5'])
            ae(filt(None, {'issues': '-1'}), ['1', '2', '3', '4', '5'])
        def ls(x):
            return list(sorted(x))
        self.assertEqual(ls(self.db.user.get('6', 'issues')), ['1', '2'])
        self.assertEqual(ls(self.db.user.get('7', 'issues')), ['3'])
        self.assertEqual(ls(self.db.user.get('10', 'issues')), ['6', '7', '8'])
        n = self.db.user.getnode('6')
        self.assertEqual(ls(n.issues), ['1', '2'])
        # Now retire some linked-to issues and retry
        self.db.issue.retire('6')
        self.db.issue.retire('2')
        self.db.issue.retire('3')
        self.db.commit()
        for filt in iiter():
            ae(filt(None, {'issues': ['3', '4']}), ['8'])
            ae(filt(None, {'issues': ['1', '4', '8']}), ['6', '8', '10'])
            ae(filt(None, {'issues.title': ['ts2']}), [])
            ae(filt(None, {'issues': ['-1']}), ['1', '2', '3', '4', '5', '7'])
            ae(filt(None, {'issues': '-1'}), ['1', '2', '3', '4', '5', '7'])
        self.assertEqual(ls(self.db.user.get('6', 'issues')), ['1'])
        self.assertEqual(ls(self.db.user.get('7', 'issues')), [])
        self.assertEqual(ls(self.db.user.get('10', 'issues')), ['7', '8'])

    def testFilteringRevLinkExpression(self):
        ae, iiter = self.filteringSetupTransitiveSearch('user')
        # We have
        # issue assignedto
        # 1:    6
        # 2:    6
        # 3:    7
        # 4:    8
        # 5:    9
        # 6:    10
        # 7:    10
        # 8:    10
        for filt in iiter():
            # Explicit 'or'
            ae(filt(None, {'issues': ['3', '4', '-4']}), ['7', '8'])
            # Implicit or with '-1'
            ae(filt(None, {'issues': ['3', '4', '-1']}),
                ['1', '2', '3', '4', '5', '7', '8'])
            # Explicit or with '-1': 3 or 4 or empty
            ae(filt(None, {'issues': ['3', '4', '-4', '-1', '-4']}),
                ['1', '2', '3', '4', '5', '7', '8'])
            # '3' and empty
            ae(filt(None, {'issues': ['3', '-1', '-3']}), [])
            # '6' and '7' and '8'
            ae(filt(None, {'issues': ['6', '7', '-3', '8', '-3']}), ['10'])
            # '6' and '7' or '1' and '2'
            ae(filt(None, {'issues': ['6', '7', '-3', '1', '2', '-3', '-4']}),
                ['6', '10'])
            # '1' or '4'
            ae(filt(None, {'issues': ['1', '4', '-4']}), ['6', '8'])

        # Now retire some linked-to issues and retry
        self.db.issue.retire('6')
        self.db.issue.retire('2')
        self.db.issue.retire('3')
        self.db.commit()
        # We have now
        # issue assignedto
        # 1:    6
        # 4:    8
        # 5:    9
        # 7:    10
        # 8:    10
        for filt in iiter():
            # Explicit 'or'
            ae(filt(None, {'issues': ['3', '4', '-4']}), ['8'])
            # Implicit or with '-1'
            ae(filt(None, {'issues': ['3', '4', '-1']}),
                ['1', '2', '3', '4', '5', '7', '8'])
            # Explicit or with '-1': 3 or 4 or empty
            ae(filt(None, {'issues': ['3', '4', '-4', '-1', '-4']}),
                ['1', '2', '3', '4', '5', '7', '8'])
            # '3' and empty
            ae(filt(None, {'issues': ['3', '-1', '-3']}), [])
            # '6' and '7' and '8'
            ae(filt(None, {'issues': ['6', '7', '-3', '8', '-3']}), [])
            # '7' and '8'
            ae(filt(None, {'issues': ['7', '8', '-3']}), ['10'])
            # '6' and '7' or '1' and '2'
            ae(filt(None, {'issues': ['6', '7', '-3', '1', '2', '-3', '-4']}),
                [])
            # '1' or '4'
            ae(filt(None, {'issues': ['1', '4', '-4']}), ['6', '8'])

    def testFilteringLinkSortSearchMultilink(self):
        ae, iiter = self.filteringSetup()
        a = 'assignedto'
        grp = (None, None)
        for filt in iiter():
            ae(filt(None, {'status.mls': '1'}, ('+','status')), ['2','3'])
            ae(filt(None, {'status.mls': '2'}, ('+','status')), ['2','3'])

    def testFilteringMultilinkAndGroup(self):
        """testFilteringMultilinkAndGroup:
        See roundup Bug 1541128: apparently grouping by something and
        searching a Multilink failed with MySQL 5.0
        """
        ae, iiter = self.filteringSetup()
        for f in iiter():
            ae(f(None, {'files': '1'}, ('-','activity'), ('+','status')), ['4'])

    def testFilteringRetired(self):
        ae, iiter = self.filteringSetup()
        self.db.issue.retire('2')
        for f in iiter():
            ae(f(None, {'status': '1'}, ('+','id'), (None,None)), ['3'])

    def testFilteringMultilink(self):
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            ae(filt(None, {'nosy': '3'}, ('+','id'), (None,None)), ['4'])
            ae(filt(None, {'nosy': '-1'}, ('+','id'), (None,None)), ['1', '2'])
            ae(filt(None, {'nosy': ['1','2']}, ('+', 'status'),
                ('-', 'deadline')), ['4', '3'])

    def testFilteringMultilinkExpression(self):
        ae, iiter = self.filteringSetup()
        kw1 = self.db.keyword.create(name='Key1')
        kw2 = self.db.keyword.create(name='Key2')
        kw3 = self.db.keyword.create(name='Key3')
        kw4 = self.db.keyword.create(name='Key4')
        self.db.issue.set('1', keywords=[kw1, kw2])
        self.db.issue.set('2', keywords=[kw1, kw3])
        self.db.issue.set('3', keywords=[kw2, kw3, kw4])
        self.db.issue.set('4', keywords=[kw1, kw2, kw4])
        self.db.commit()
        kw = 'keywords'
        for filt in iiter():
            # '1' and '2'
            ae(filt(None, {kw: ['1', '2', '-3']}),
               ['1', '4'])
            # ('2' and '4') and '1'
            ae(filt(None, {kw: ['1', '2', '4', '-3', '-3']}),
               ['4'])
            # not '4' and '3'
            ae(filt(None, {kw: ['3', '4', '-2', '-3']}),
               ['2'])
            # (not '4' and '3') and '2'
            ae(filt(None, {kw: ['2', '3', '4', '-2', '-3', '-3']}),
               [])
            # '1' or '2' without explicit 'or'
            ae(filt(None, {kw: ['1', '2']}),
               ['1', '2', '3', '4'])
            # '1' or '2' with explicit 'or'
            ae(filt(None, {kw: ['1', '2', '-4']}),
               ['1', '2', '3', '4'])
            # '3' or '4' without explicit 'or'
            ae(filt(None, {kw: ['3', '4']}),
               ['2', '3', '4'])
            # '3' or '4' with explicit 'or'
            ae(filt(None, {kw: ['3', '4', '-4']}),
               ['2', '3', '4'])
            # ('3' and '4') or ('1' and '2')
            ae(filt(None, {kw: ['3', '4', '-3', '1', '2', '-3', '-4']}),
               ['1', '3', '4'])
            # '2' and empty
            ae(filt(None, {kw: ['2', '-1', '-3']}),
               [])
        self.db.issue.set('1', keywords=[])
        self.db.commit()
        for filt in iiter():
            ae(filt(None, {kw: ['-1']}),
               ['1'])
            # '3' or empty (without explicit 'or')
            ae(filt(None, {kw: ['3', '-1']}),
               ['1', '2', '3'])
            # '3' or empty (with explicit 'or')
            ae(filt(None, {kw: ['3', '-1', '-4']}),
               ['1', '2', '3'])
            # empty or '3' (with explicit 'or')
            ae(filt(None, {kw: ['-1', '3', '-4']}),
               ['1', '2', '3'])
            # '3' and empty (should always return empty list)
            ae(filt(None, {kw: ['3', '-1', '-3']}),
               [])
            # empty and '3' (should always return empty list)
            ae(filt(None, {kw: ['3', '-1', '-3']}),
               [])
            # ('4' and empty) or ('3' or empty)
            ae(filt(None, {kw: ['4', '-1', '-3', '3', '-1', '-4', '-4']}),
               ['1', '2', '3'])

    def testFilteringTwoMultilinksExpression(self):
        ae, iiter = self.filteringSetup()
        kw1 = self.db.keyword.create(name='Key1', order=10)
        kw2 = self.db.keyword.create(name='Key2', order=20)
        kw3 = self.db.keyword.create(name='Key3', order=30)
        kw4 = self.db.keyword.create(name='Key4', order=40)
        self.db.issue.set('1', keywords=[kw1, kw2])
        self.db.issue.set('2', keywords=[kw1, kw3])
        self.db.issue.set('3', keywords=[kw2, kw3, kw4])
        self.db.issue.set('4', keywords=[])
        self.db.issue.set('1', keywords2=[kw3, kw4])
        self.db.issue.set('2', keywords2=[kw2, kw3])
        self.db.issue.set('3', keywords2=[kw1, kw3, kw4])
        self.db.issue.set('4', keywords2=[])
        self.db.commit()
        kw = 'keywords'
        kw2 = 'keywords2'
        for filt in iiter():
            # kw: '1' and '3' kw2: '2' and '3'
            ae(filt(None, {kw: ['1', '3', '-3'], kw2: ['2', '3', '-3']}), ['2'])
            # kw: empty kw2: empty
            ae(filt(None, {kw: ['-1'], kw2: ['-1']}), ['4'])
            # kw: empty kw2: empty
            ae(filt(None, {kw: [], kw2: []}), ['4'])
            # look for both keyword name and order
            ae(filt(None, {'keywords.name': 'y4', 'keywords.order': 40}), ['3'])
            # look for both keyword and order non-matching
            ae(filt(None, {kw: '3', 'keywords.order': 40}), [])
            # look for both keyword and order non-matching with kw and kw2
            ae(filt(None, {kw: '3', 'keywords2.order': 40}), ['3'])

    def testFilteringRevMultilink(self):
        ae, iiter = self.filteringSetupTransitiveSearch('user')
        ni = 'nosy_issues'
        self.db.issue.set('6', nosy=['3', '4', '5'])
        self.db.issue.set('7', nosy=['5'])
        # After this setup we have the following values for nosy:
        # issue   nosy
        # 1:      4
        # 2:      5
        # 3:
        # 4:
        # 5:
        # 6:      3, 4, 5
        # 7:      5
        # 8:
        for filt in iiter():
            ae(filt(None, {ni: ['1', '2']}), ['4', '5'])
            ae(filt(None, {ni: ['6','7']}), ['3', '4', '5'])
            ae(filt(None, {'nosy_issues.title': ['ts2']}), ['5'])
            ae(filt(None, {ni: ['-1']}), ['1', '2', '6', '7', '8', '9', '10'])
            ae(filt(None, {ni: '-1'}), ['1', '2', '6', '7', '8', '9', '10'])
        def ls(x):
            return list(sorted(x))
        self.assertEqual(ls(self.db.user.get('4', ni)), ['1', '6'])
        self.assertEqual(ls(self.db.user.get('5', ni)), ['2', '6', '7'])
        n = self.db.user.getnode('4')
        self.assertEqual(ls(n.nosy_issues), ['1', '6'])
        # Now retire some linked-to issues and retry
        self.db.issue.retire('2')
        self.db.issue.retire('6')
        self.db.commit()
        for filt in iiter():
            ae(filt(None, {ni: ['1', '2']}), ['4'])
            ae(filt(None, {ni: ['6','7']}), ['5'])
            ae(filt(None, {'nosy_issues.title': ['ts2']}), [])
            ae(filt(None, {ni: ['-1']}),
                ['1', '2', '3', '6', '7', '8', '9', '10'])
            ae(filt(None, {ni: '-1'}),
                ['1', '2', '3', '6', '7', '8', '9', '10'])
        self.assertEqual(ls(self.db.user.get('4', ni)), ['1'])
        self.assertEqual(ls(self.db.user.get('5', ni)), ['7'])

    def testFilteringRevMultilinkQ2(self):
        ae, iiter = self.filteringSetupTransitiveSearch('user')
        ni = 'nosy_issues'
        nis = 'nosy_issues.status'
        self.db.issue.set('6', nosy=['3', '4', '5'])
        self.db.issue.set('7', nosy=['5'])
        self.db.commit()
        # After this setup we have the following values for nosy:
        # The issues '1', '3', '5', '7' have status '2'
        # issue   nosy
        # 1:      4
        # 2:      5
        # 3:
        # 4:
        # 5:
        # 6:      3, 4, 5
        # 7:      5
        # 8:
        for filt in iiter():
            # status of issue is '2'
            ae(filt(None, {nis: ['2']}),
               ['4', '5'])
            # Issue non-empty and status of issue is '2'
            ae(filt(None, {nis: ['2'], ni:['-1', '-2']}),
               ['4', '5'])
            # empty and status '2'
            # This is the test-case for issue2551119
            ae(filt(None, {nis: ['2'], ni:['-1']}), [])

    def testFilteringRevMultilinkExpression(self):
        ae, iiter = self.filteringSetupTransitiveSearch('user')
        ni = 'nosy_issues'
        self.db.issue.set('6', nosy=['3', '4', '5'])
        self.db.issue.set('7', nosy=['5'])
        # After this setup we have the following values for nosy:
        # issue   nosy
        # 1:      4
        # 2:      5
        # 3:
        # 4:
        # 5:
        # 6:      3, 4, 5
        # 7:      5
        # 8:
        # Retire users '9' and '10' to reduce list
        self.db.user.retire('9')
        self.db.user.retire('10')
        self.db.commit()
        for filt in iiter():
            # not empty
            ae(filt(None, {ni: ['-1', '-2']}), ['3', '4', '5'])
            # '1' or '2'
            ae(filt(None, {ni: ['1', '2', '-4']}), ['4', '5'])
            # '6' or '7'
            ae(filt(None, {ni: ['6', '7', '-4']}), ['3', '4', '5'])
            # '6' and '7'
            ae(filt(None, {ni: ['6', '7', '-3']}), ['5'])
            # '6' and not '1'
            ae(filt(None, {ni: ['6', '1', '-2', '-3']}), ['3', '5'])
            # '2' or empty (implicit or)
            ae(filt(None, {ni: ['-1', '2']}), ['1', '2', '5', '6', '7', '8'])
            # '2' or empty (explicit or)
            ae(filt(None, {ni: ['-1', '2', '-4']}),
               ['1', '2', '5', '6', '7', '8'])
            # empty or '2' (explicit or)
            ae(filt(None, {ni: ['2', '-1', '-4']}),
               ['1', '2', '5', '6', '7', '8'])
            # '2' and empty (should always return empty list)
            ae(filt(None, {ni: ['-1', '2', '-3']}), [])
            # empty and '2' (should always return empty list)
            ae(filt(None, {ni: ['2', '-1', '-3']}), [])
            # ('4' and empty) or ('2' or empty)
            ae(filt(None, {ni: ['4', '-1', '-3', '2', '-1', '-4', '-4']}),
               ['1', '2', '5', '6', '7', '8'])
        # Retire issues 2, 6 and retry
        self.db.issue.retire('2')
        self.db.issue.retire('6')
        self.db.commit()
        # After this setup we have the following values for nosy:
        # issue   nosy
        # 1:      4
        # 3:
        # 4:
        # 5:
        # 7:      5
        # 8:
        for filt in iiter():
            # not empty
            ae(filt(None, {ni: ['-1', '-2']}), ['4', '5'])
            # '1' or '2' (implicit)
            ae(filt(None, {ni: ['1', '2']}), ['4'])
            # '1' or '2'
            ae(filt(None, {ni: ['1', '2', '-4']}), ['4'])
            # '6' or '7'
            ae(filt(None, {ni: ['6', '7', '-4']}), ['5'])
            # '6' and '7'
            ae(filt(None, {ni: ['6', '7', '-3']}), [])
            # '6' and not '1'
            ae(filt(None, {ni: ['6', '1', '-2', '-3']}), [])
            # not '1'
            ae(filt(None, {ni: ['1', '-2']}),
               ['1', '2', '3', '5', '6', '7', '8'])
            # '2' or empty (implicit or)
            ae(filt(None, {ni: ['-1', '2']}), ['1', '2', '3', '6', '7', '8'])
            # '2' or empty (explicit or)
            ae(filt(None, {ni: ['-1', '2', '-4']}),
               ['1', '2', '3', '6', '7', '8'])
            # empty or '2' (explicit or)
            ae(filt(None, {ni: ['2', '-1', '-4']}),
               ['1', '2', '3', '6', '7', '8'])
            # '2' and empty (should always return empty list)
            ae(filt(None, {ni: ['-1', '2', '-3']}), [])
            # empty and '2' (should always return empty list)
            ae(filt(None, {ni: ['2', '-1', '-3']}), [])
            # ('4' and empty) or ('2' or empty)
            ae(filt(None, {ni: ['4', '-1', '-3', '2', '-1', '-4', '-4']}),
               ['1', '2', '3', '6', '7', '8'])

    def testFilteringMany(self):
        ae, iiter = self.filteringSetup()
        for f in iiter():
            ae(f(None, {'nosy': '2', 'status': '1'}, ('+','id'), (None,None)),
                ['3'])

    def testFilteringRangeBasic(self):
        ae, iiter = self.filteringSetup()
        d = 'deadline'
        for f in iiter():
            ae(f(None, {d: 'from 2003-02-10 to 2003-02-23'}), ['1','3'])
            ae(f(None, {d: '2003-02-10; 2003-02-23'}), ['1','3'])
            ae(f(None, {d: '; 2003-02-16'}), ['2'])

    def testFilteringRangeTwoSyntaxes(self):
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            ae(filt(None, {'deadline': 'from 2003-02-16'}), ['1', '3', '4'])
            ae(filt(None, {'deadline': '2003-02-16;'}), ['1', '3', '4'])

    def testFilteringRangeYearMonthDay(self):
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            ae(filt(None, {'deadline': '2002'}), [])
            ae(filt(None, {'deadline': '2003'}), ['1', '2', '3'])
            ae(filt(None, {'deadline': '2004'}), ['4'])
            ae(filt(None, {'deadline': '2003-02-16'}), ['1'])
            ae(filt(None, {'deadline': '2003-02-17'}), [])

    def testFilteringRangeMonths(self):
        ae, iiter = self.filteringSetup()
        for month in range(1, 13):
            for n in range(1, month+1):
                i = self.db.issue.create(title='%d.%d'%(month, n),
                    deadline=date.Date('2001-%02d-%02d.00:00'%(month, n)))
        self.db.commit()

        for month in range(1, 13):
            for filt in iiter():
                r = filt(None, dict(deadline='2001-%02d'%month))
                assert len(r) == month, 'month %d != length %d'%(month, len(r))

    def testFilteringDateRangeMulti(self):
        ae, iiter = self.filteringSetup()
        self.db.issue.create(title='no deadline')
        self.db.commit()
        for filt in iiter():
            r = filt (None, dict(deadline='-'))
            self.assertEqual(r, ['5'])
            r = filt (None, dict(deadline=';2003-02-01,2004;'))
            self.assertEqual(r, ['2', '4'])
            r = filt (None, dict(deadline='-,;2003-02-01,2004;'))
            self.assertEqual(r, ['2', '4', '5'])

    def testFilteringRangeInterval(self):
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            ae(filt(None, {'foo': 'from 0:50 to 2:00'}), ['1'])
            ae(filt(None, {'foo': 'from 0:50 to 1d 2:00'}), ['1', '2'])
            ae(filt(None, {'foo': 'from 5:50'}), ['2'])
            ae(filt(None, {'foo': 'to 0:05'}), [])

    def testFilteringRangeGeekInterval(self):
        ae, iiter = self.filteringSetup()
        # Note: When querying, create date one minute later than the
        # timespan later queried to avoid race conditions where the
        # creation of the deadline is more than a second ago when
        # queried -- in that case we wouldn't get the expected result.
        # By extending the interval by a minute we would need a very
        # slow machine for this test to fail :-)
        for issue in (
                { 'deadline': date.Date('. -2d') + date.Interval ('00:01')},
                { 'deadline': date.Date('. -1d') + date.Interval ('00:01')},
                { 'deadline': date.Date('. -8d') + date.Interval ('00:01')},
                ):
            self.db.issue.create(**issue)
        for filt in iiter():
            ae(filt(None, {'deadline': '-2d;'}), ['5', '6'])
            ae(filt(None, {'deadline': '-1d;'}), ['6'])
            ae(filt(None, {'deadline': '-1w;'}), ['5', '6'])
            ae(filt(None, {'deadline': '. -2d;'}), ['5', '6'])
            ae(filt(None, {'deadline': '. -1d;'}), ['6'])
            ae(filt(None, {'deadline': '. -1w;'}), ['5', '6'])

    def testFilteringIntervalSort(self):
        # 1: '1:10'
        # 2: '1d'
        # 3: None
        # 4: '0:10'
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            # ascending should sort None, 1:10, 1d
            ae(filt(None, {}, ('+','foo'), (None,None)), ['3', '4', '1', '2'])
            # descending should sort 1d, 1:10, None
            ae(filt(None, {}, ('-','foo'), (None,None)), ['2', '1', '4', '3'])

    def testFilteringStringSort(self):
        # 1: 'issue one'
        # 2: 'issue two'
        # 3: 'issue three'
        # 4: 'non four'
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            ae(filt(None, {}, ('+','title')), ['1', '3', '2', '4'])
            ae(filt(None, {}, ('-','title')), ['4', '2', '3', '1'])
        # Test string case: For now allow both, w/wo case matching.
        # 1: 'issue one'
        # 2: 'issue two'
        # 3: 'Issue three'
        # 4: 'non four'
        self.db.issue.set('3', title='Issue three')
        for filt in iiter():
            ae(filt(None, {}, ('+','title')), ['1', '3', '2', '4'])
            ae(filt(None, {}, ('-','title')), ['4', '2', '3', '1'])
        # Obscure bug in anydbm backend trying to convert to number
        # 1: '1st issue'
        # 2: '2'
        # 3: 'Issue three'
        # 4: 'non four'
        self.db.issue.set('1', title='1st issue')
        self.db.issue.set('2', title='2')
        for filt in iiter():
            ae(filt(None, {}, ('+','title')), ['1', '2', '3', '4'])
            ae(filt(None, {}, ('-','title')), ['4', '3', '2', '1'])

    def testFilteringMultilinkSort(self):
        # 1: []                 Reverse:  1: []
        # 2: []                           2: []
        # 3: ['admin','fred']             3: ['fred','admin']
        # 4: ['admin','bleep','fred']     4: ['fred','bleep','admin']
        # Note the sort order for the multilink doen't change when
        # reversing the sort direction due to the re-sorting of the
        # multilink!
        # Note that we don't test filter_iter here, Multilink sort-order
        # isn't defined for that.
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            if filt.__name__ != 'filter':
                continue
            ae(filt(None, {}, ('+','nosy'), (None,None)), ['1', '2', '4', '3'])
            ae(filt(None, {}, ('-','nosy'), (None,None)), ['4', '3', '1', '2'])

    def testFilteringMultilinkSortGroup(self):
        # 1: status: 2 "in-progress" nosy: []
        # 2: status: 1 "unread"      nosy: []
        # 3: status: 1 "unread"      nosy: ['admin','fred']
        # 4: status: 3 "testing"     nosy: ['admin','bleep','fred']
        # Note that we don't test filter_iter here, Multilink sort-order
        # isn't defined for that.
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            if filt.__name__ != 'filter':
                continue
            ae(filt(None, {}, ('+','nosy'), ('+','status')),
                ['1', '4', '2', '3'])
            ae(filt(None, {}, ('-','nosy'), ('+','status')),
                ['1', '4', '3', '2'])
            ae(filt(None, {}, ('+','nosy'), ('-','status')),
                ['2', '3', '4', '1'])
            ae(filt(None, {}, ('-','nosy'), ('-','status')),
                ['3', '2', '4', '1'])
            ae(filt(None, {}, ('+','status'), ('+','nosy')),
                ['1', '2', '4', '3'])
            ae(filt(None, {}, ('-','status'), ('+','nosy')),
                ['2', '1', '4', '3'])
            ae(filt(None, {}, ('+','status'), ('-','nosy')),
                ['4', '3', '1', '2'])
            ae(filt(None, {}, ('-','status'), ('-','nosy')),
                ['4', '3', '2', '1'])

    def testFilteringLinkSortGroup(self):
        # 1: status: 2 -> 'i', priority: 3 -> 1
        # 2: status: 1 -> 'u', priority: 3 -> 1
        # 3: status: 1 -> 'u', priority: 2 -> 3
        # 4: status: 3 -> 't', priority: 2 -> 3
        ae, iiter = self.filteringSetup()
        for filt in iiter():
            ae(filt(None, {}, ('+','status'), ('+','priority')),
                ['1', '2', '4', '3'])
            ae(filt(None, {'priority':'2'}, ('+','status'), ('+','priority')),
                ['4', '3'])
            ae(filt(None, {'priority.order':'3'}, ('+','status'),
                ('+','priority')), ['4', '3'])
            ae(filt(None, {'priority':['2','3']}, ('+','priority'),
                ('+','status')), ['1', '4', '2', '3'])
            ae(filt(None, {}, ('+','priority'), ('+','status')),
                ['1', '4', '2', '3'])

    def testFilteringDateSort(self):
        # '1': '2003-02-16.22:50'
        # '2': '2003-01-01.00:00'
        # '3': '2003-02-18'
        # '4': '2004-03-08'
        ae, iiter = self.filteringSetup()
        for f in iiter():
            # ascending
            ae(f(None, {}, ('+','deadline'), (None,None)), ['2', '1', '3', '4'])
            # descending
            ae(f(None, {}, ('-','deadline'), (None,None)), ['4', '3', '1', '2'])

    def testFilteringDateSortPriorityGroup(self):
        # '1': '2003-02-16.22:50'  1 => 2
        # '2': '2003-01-01.00:00'  3 => 1
        # '3': '2003-02-18'        2 => 3
        # '4': '2004-03-08'        1 => 2
        ae, iiter = self.filteringSetup()

        for filt in iiter():
            # ascending
            ae(filt(None, {}, ('+','deadline'), ('+','priority')),
                ['2', '1', '3', '4'])
            ae(filt(None, {}, ('-','deadline'), ('+','priority')),
                ['1', '2', '4', '3'])
            # descending
            ae(filt(None, {}, ('+','deadline'), ('-','priority')),
                ['3', '4', '2', '1'])
            ae(filt(None, {}, ('-','deadline'), ('-','priority')),
                ['4', '3', '1', '2'])

    def testFilteringTransitiveLinkUser(self):
        ae, iiter = self.filteringSetupTransitiveSearch('user')
        for f in iiter():
            ae(f(None, {'supervisor.username': 'ceo'}, ('+','username')),
                ['4', '5'])
            ae(f(None, {'supervisor.supervisor.username': 'ceo'},
                ('+','username')), ['6', '7', '8', '9', '10'])
            ae(f(None, {'supervisor.supervisor': '3'}, ('+','username')),
                ['6', '7', '8', '9', '10'])
            ae(f(None, {'supervisor.supervisor.id': '3'}, ('+','username')),
                ['6', '7', '8', '9', '10'])
            ae(f(None, {'supervisor.username': 'grouplead1'}, ('+','username')),
                ['6', '7'])
            ae(f(None, {'supervisor.username': 'grouplead2'}, ('+','username')),
                ['8', '9', '10'])
            ae(f(None, {'supervisor.username': 'grouplead2',
                'supervisor.supervisor.username': 'ceo'}, ('+','username')),
                ['8', '9', '10'])
            ae(f(None, {'supervisor.supervisor': '3', 'supervisor': '4'},
                ('+','username')), ['6', '7'])

    def testFilteringTransitiveLinkUserLimit(self):
        ae, iiter = self.filteringSetupTransitiveSearch('user')
        for f in iiter():
            ae(f(None, {'supervisor.username': 'ceo'}, ('+','username'),
                 limit=1), ['4'])
            ae(f(None, {'supervisor.supervisor.username': 'ceo'},
                ('+','username'), limit=4), ['6', '7', '8', '9'])
            ae(f(None, {'supervisor.supervisor': '3'}, ('+','username'),
                limit=2, offset=2), ['8', '9'])
            ae(f(None, {'supervisor.supervisor.id': '3'}, ('+','username'),
                limit=3, offset=1), ['7', '8', '9'])
            ae(f(None, {'supervisor.username': 'grouplead2'}, ('+','username'),
                limit=2, offset=2), ['10'])
            ae(f(None, {'supervisor.username': 'grouplead2',
                'supervisor.supervisor.username': 'ceo'}, ('+','username'),
                limit=4, offset=3), [])
            ae(f(None, {'supervisor.supervisor': '3', 'supervisor': '4'},
                ('+','username'), limit=1, offset=5), [])

    def testFilteringTransitiveLinkSort(self):
        ae, iiter = self.filteringSetupTransitiveSearch()
        ae, uiter = self.iterSetup('user')
        # Need to make ceo his own (and first two users') supervisor,
        # otherwise we will depend on sorting order of NULL values.
        # Leave that to a separate test.
        self.db.user.set('1', supervisor = '3')
        self.db.user.set('2', supervisor = '3')
        self.db.user.set('3', supervisor = '3')
        for ufilt in uiter():
            ae(ufilt(None, {'supervisor':'3'}, []), ['1', '2', '3', '4', '5'])
            ae(ufilt(None, {}, [('+','supervisor.supervisor.supervisor'),
                ('+','supervisor.supervisor'), ('+','supervisor'),
                ('+','username')]),
                ['1', '3', '2', '4', '5', '6', '7', '8', '9', '10'])
            ae(ufilt(None, {}, [('+','supervisor.supervisor.supervisor'),
                ('-','supervisor.supervisor'), ('-','supervisor'),
                ('+','username')]),
                ['8', '9', '10', '6', '7', '1', '3', '2', '4', '5'])
        for f in iiter():
            ae(f(None, {}, [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('+','assignedto.supervisor'), ('+','assignedto')]),
                ['1', '2', '3', '4', '5', '6', '7', '8'])
            ae(f(None, {}, [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('-','assignedto.supervisor'), ('+','assignedto')]),
                ['4', '5', '6', '7', '8', '1', '2', '3'])
            ae(f(None, {}, [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('+','assignedto.supervisor'), ('+','assignedto'),
                ('-','status')]),
                ['2', '1', '3', '4', '5', '6', '8', '7'])
            ae(f(None, {}, [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('+','assignedto.supervisor'), ('+','assignedto'),
                ('+','status')]),
                ['1', '2', '3', '4', '5', '7', '6', '8'])
            ae(f(None, {}, [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('-','assignedto.supervisor'), ('+','assignedto'),
                ('+','status')]), ['4', '5', '7', '6', '8', '1', '2', '3'])
            ae(f(None, {'assignedto':['6','7','8','9','10']},
                [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('-','assignedto.supervisor'), ('+','assignedto'),
                ('+','status')]), ['4', '5', '7', '6', '8', '1', '2', '3'])
            ae(f(None, {'assignedto':['6','7','8','9']},
                [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('-','assignedto.supervisor'), ('+','assignedto'),
                ('+','status')]), ['4', '5', '1', '2', '3'])

    def testFilteringTransitiveLinkSortNull(self):
        """Check sorting of NULL values"""
        ae, iiter = self.filteringSetupTransitiveSearch()
        ae, uiter = self.iterSetup('user')
        for ufilt in uiter():
            ae(ufilt(None, {}, [('+','supervisor.supervisor.supervisor'),
                ('+','supervisor.supervisor'), ('+','supervisor'),
                ('+','username')]),
                ['1', '3', '2', '4', '5', '6', '7', '8', '9', '10'])
            ae(ufilt(None, {}, [('+','supervisor.supervisor.supervisor'),
                ('-','supervisor.supervisor'), ('-','supervisor'),
                ('+','username')]),
                ['8', '9', '10', '6', '7', '4', '5', '1', '3', '2'])
        for f in iiter():
            ae(f(None, {}, [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('+','assignedto.supervisor'), ('+','assignedto')]),
                ['1', '2', '3', '4', '5', '6', '7', '8'])
            ae(f(None, {}, [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('-','assignedto.supervisor'), ('+','assignedto')]),
                ['4', '5', '6', '7', '8', '1', '2', '3'])

    def testFilteringTransitiveLinkIssue(self):
        ae, iiter = self.filteringSetupTransitiveSearch()
        for filt in iiter():
            ae(filt(None, {'assignedto.supervisor.username': 'grouplead1'},
                ('+','id')), ['1', '2', '3'])
            ae(filt(None, {'assignedto.supervisor.username': 'grouplead2'},
                ('+','id')), ['4', '5', '6', '7', '8'])
            ae(filt(None, {'assignedto.supervisor.username': 'grouplead2',
                           'status': '1'}, ('+','id')), ['4', '6', '8'])
            ae(filt(None, {'assignedto.supervisor.username': 'grouplead2',
                           'status': '2'}, ('+','id')), ['5', '7'])
            ae(filt(None, {'assignedto.supervisor.username': ['grouplead2'],
                           'status': '2'}, ('+','id')), ['5', '7'])
            ae(filt(None, {'assignedto.supervisor': ['4', '5'], 'status': '2'},
                ('+','id')), ['1', '3', '5', '7'])

    def testFilteringTransitiveMultilink(self):
        ae, iiter = self.filteringSetupTransitiveSearch()
        for filt in iiter():
            ae(filt(None, {'messages.author.username': 'grouplead1'},
                ('+','id')), [])
            ae(filt(None, {'messages.author': '6'},
                ('+','id')), ['1', '2'])
            ae(filt(None, {'messages.author.id': '6'},
                ('+','id')), ['1', '2'])
            ae(filt(None, {'messages.author.username': 'worker1'},
                ('+','id')), ['1', '2'])
            ae(filt(None, {'messages.author': '10'},
                ('+','id')), ['6', '7', '8'])
            ae(filt(None, {'messages.author': '9'},
                ('+','id')), ['5', '8'])
            ae(filt(None, {'messages.author': ['9', '10']},
                ('+','id')), ['5', '6', '7', '8'])
            ae(filt(None, {'messages.author': ['8', '9']},
                ('+','id')), ['4', '5', '8'])
            ae(filt(None, {'messages.author': ['8', '9'], 'status' : '1'},
                ('+','id')), ['4', '8'])
            ae(filt(None, {'messages.author': ['8', '9'], 'status' : '2'},
                ('+','id')), ['5'])
            ae(filt(None, {'messages.author': ['8', '9', '10'],
                'messages.date': '2006-01-22.21:00;2006-01-23'}, ('+','id')),
                ['6', '7', '8'])
            ae(filt(None, {'nosy.supervisor.username': 'ceo'},
                ('+','id')), ['1', '2'])
            ae(filt(None, {'messages.author': ['6', '9']},
                ('+','id')), ['1', '2', '5', '8'])
            ae(filt(None, {'messages': ['5', '7']},
                ('+','id')), ['3', '5', '8'])
            ae(filt(None, {'messages.author': ['6', '9'],
                'messages': ['5', '7']}, ('+','id')), ['5', '8'])

    def testFilteringTransitiveMultilinkSort(self):
        # Note that we don't test filter_iter here, Multilink sort-order
        # isn't defined for that.
        ae, iiter = self.filteringSetupTransitiveSearch()
        for filt in iiter():
            if filt.__name__ != 'filter':
                continue
            ae(filt(None, {}, [('+','messages.author')]),
                ['1', '2', '3', '4', '5', '8', '6', '7'])
            ae(filt(None, {}, [('-','messages.author')]),
                ['8', '6', '7', '5', '4', '3', '1', '2'])
            ae(filt(None, {}, [('+','messages.date')]),
                ['6', '7', '8', '5', '4', '3', '1', '2'])
            ae(filt(None, {}, [('-','messages.date')]),
                ['1', '2', '3', '4', '8', '5', '6', '7'])
            ae(filt(None, {}, [('+','messages.author'),('+','messages.date')]),
                ['1', '2', '3', '4', '5', '8', '6', '7'])
            ae(filt(None, {}, [('-','messages.author'),('+','messages.date')]),
                ['8', '6', '7', '5', '4', '3', '1', '2'])
            ae(filt(None, {}, [('+','messages.author'),('-','messages.date')]),
                ['1', '2', '3', '4', '5', '8', '6', '7'])
            ae(filt(None, {}, [('-','messages.author'),('-','messages.date')]),
                ['8', '6', '7', '5', '4', '3', '1', '2'])
            ae(filt(None, {}, [('+','messages.author'),('+','assignedto')]),
                ['1', '2', '3', '4', '5', '8', '6', '7'])
            ae(filt(None, {}, [('+','messages.author'),
                ('-','assignedto.supervisor'),('-','assignedto')]),
                ['1', '2', '3', '4', '5', '8', '6', '7'])
            ae(filt(None, {},
                [('+','messages.author.supervisor.supervisor.supervisor'),
                ('+','messages.author.supervisor.supervisor'),
                ('+','messages.author.supervisor'), ('+','messages.author')]),
                ['1', '2', '3', '4', '5', '6', '7', '8'])
        self.db.user.setorderprop('age')
        self.db.msg.setorderprop('date')
        for filt in iiter():
            if filt.__name__ != 'filter':
                continue
            ae(filt(None, {}, [('+','messages'), ('+','messages.author')]),
                ['6', '7', '8', '5', '4', '3', '1', '2'])
            ae(filt(None, {}, [('+','messages.author'), ('+','messages')]),
                ['6', '7', '8', '5', '4', '3', '1', '2'])
        self.db.msg.setorderprop('author')
        for filt in iiter():
            if filt.__name__ != 'filter':
                continue
            # Orderprop is a Link/Multilink:
            # messages are sorted by orderprop().labelprop(), i.e. by
            # author.username, *not* by author.orderprop() (author.age)!
            ae(filt(None, {}, [('+','messages')]),
                ['1', '2', '3', '4', '5', '8', '6', '7'])
            ae(filt(None, {}, [('+','messages.author'), ('+','messages')]),
                ['6', '7', '8', '5', '4', '3', '1', '2'])
            # The following will sort by
            # author.supervisor.username and then by
            # author.username
            # I've resited the tempation to implement recursive orderprop
            # here: There could even be loops if several classes specify a
            # Link or Multilink as the orderprop...
            # msg: 4: worker1 (id  5) : grouplead1 (id 4) ceo (id 3)
            # msg: 5: worker2 (id  7) : grouplead1 (id 4) ceo (id 3)
            # msg: 6: worker3 (id  8) : grouplead2 (id 5) ceo (id 3)
            # msg: 7: worker4 (id  9) : grouplead2 (id 5) ceo (id 3)
            # msg: 8: worker5 (id 10) : grouplead2 (id 5) ceo (id 3)
            # issue 1: messages 4   sortkey:[[grouplead1], [worker1], 1]
            # issue 2: messages 4   sortkey:[[grouplead1], [worker1], 2]
            # issue 3: messages 5   sortkey:[[grouplead1], [worker2], 3]
            # issue 4: messages 6   sortkey:[[grouplead2], [worker3], 4]
            # issue 5: messages 7   sortkey:[[grouplead2], [worker4], 5]
            # issue 6: messages 8   sortkey:[[grouplead2], [worker5], 6]
            # issue 7: messages 8   sortkey:[[grouplead2], [worker5], 7]
            # issue 8: messages 7,8 sortkey:[[grouplead2, grouplead2], ...]
        self.db.user.setorderprop('supervisor')
        for filt in iiter():
            if filt.__name__ != 'filter':
                continue
            ae(filt(None, {}, [('+','messages.author'), ('-','messages')]),
                ['3', '1', '2', '6', '7', '5', '4', '8'])

    def testFilteringSortId(self):
        ae, iiter = self.filteringSetupTransitiveSearch('user')
        for filt in iiter():
            ae(filt(None, {}, ('+','id')),
                ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])

    def testFilteringRetiredString(self):
        ae, iiter = self.filteringSetup()
        self.db.issue.retire('1')
        self.db.commit()
        r = { None: (['1'], ['1'], ['1'], ['1', '2', '3'], [])
            , True: (['1'], ['1'], ['1'], ['1'], [])
            , False: ([], [], [], ['2', '3'], [])
            }
        for filt in iiter():
            for retire in True, False, None:
                ae(filt(None, {'title': ['one']}, ('+','id'),
                   retired=retire), r[retire][0])
                ae(filt(None, {'title': ['issue one']}, ('+','id'),
                   retired=retire), r[retire][1])
                ae(filt(None, {'title': ['issue', 'one']}, ('+','id'),
                   retired=retire), r[retire][2])
                ae(filt(None, {'title': ['issue']}, ('+','id'),
                   retired=retire), r[retire][3])
                ae(filt(None, {'title': ['one', 'two']}, ('+','id'),
                   retired=retire), r[retire][4])

# XXX add sorting tests for other types

    # nuke and re-create db for restore
    def nukeAndCreate(self):
        # shut down this db and nuke it
        self.db.close()
        self.nuke_database()

        # open a new, empty database
        os.makedirs(config.DATABASE + '/files')
        self.db = self.module.Database(config, 'admin')
        setupSchema(self.db, 0, self.module)

    def testImportExport(self):
        # use the filtering setup to create a bunch of items
        ae, dummy = self.filteringSetup()
        # Get some stuff into the journal for testing import/export of
        # journal data:
        self.db.user.set('4', password = password.Password('xyzzy'))
        self.db.user.set('4', age = 3)
        self.db.user.set('4', assignable = True)
        self.db.issue.set('1', title = 'i1', status = '3')
        self.db.issue.set('1', deadline = date.Date('2007'))
        self.db.issue.set('1', foo = date.Interval('1:20'))
        p = self.db.priority.create(name = 'some_prio_without_order')
        self.db.commit()
        self.db.user.set('4', password = password.Password('123xyzzy'))
        self.db.user.set('4', assignable = False)
        self.db.priority.set(p, order = '4711')
        self.db.commit()

        self.db.user.retire('3')
        self.db.issue.retire('2')

        # Key fields must be unique. There can only be one unretired
        # object with a given key value. When importing verify that
        # having the unretired object with a key value before a retired
        # object with the same key value is handled properly.

        # Since the order of the exported objects is not consistant
        # across backends, we sort the objects by id (as an int) and
        # make sure that the active (non-retired) entry sorts before
        # the retired entry.
        active_dupe_id = self.db.user.create(username="duplicate",
                                             roles='User',
            password=password.Password('sekrit'), address='dupe1@example.com')
        self.db.user.retire(active_dupe_id) # allow us to create second dupe

        retired_dupe_id = self.db.user.create(username="duplicate",
                                              roles='User',
            password=password.Password('sekrit'), address='dupe2@example.com')
        self.db.user.retire(retired_dupe_id)
        self.db.user.restore(active_dupe_id) # unretire lower numbered id
        self.db.commit()

        # grab snapshot of the current database
        orig = {}
        origj = {}
        for cn,klass in self.db.classes.items():
            cl = orig[cn] = {}
            jn = origj[cn] = {}
            for id in klass.list():
                it = cl[id] = {}
                jn[id] = self.db.getjournal(cn, id)
                for name in klass.getprops().keys():
                    it[name] = klass.get(id, name)

        os.mkdir('_test_export')
        try:
            # grab the export
            export = {}
            journals = {}
            active_dupe_id_first = -1 # -1 unknown, False or True
            for cn,klass in self.db.classes.items():
                names = klass.export_propnames()
                cl = export[cn] = [names+['is retired']]
                classname = klass.classname
                nodeids =  klass.getnodeids()
                # sort to enforce retired/unretired order
                nodeids.sort(key=int)
                for id in nodeids:
                    if (classname == 'user' and 
                       id == retired_dupe_id and 
                       active_dupe_id_first == -1):
                       active_dupe_id_first = False
                    if (classname == 'user' and 
                       id == active_dupe_id and 
                       active_dupe_id_first == -1):
                        active_dupe_id_first = True
                    cl.append(klass.export_list(names, id))
                    if hasattr(klass, 'export_files'):
                        klass.export_files('_test_export', id)
                journals[cn] = klass.export_journals()

            self.nukeAndCreate()

            if not active_dupe_id_first:
                # verify that the test is configured properly to
                # trigger the exception code to handle uniqueness
                # failure.
                self.fail("Setup failure: active user id not first.")

            # import
            with self._caplog.at_level(logging.INFO,
                                       logger="roundup.hyperdb.backend"):
            # not supported in python2, so use caplog rather than len(log)
            #  X in log[0] ... 
            #    with self.assertLogs('roundup.hyperdb.backend',
            #                     level="INFO") as log:
              for cn, items in export.items():
                  klass = self.db.classes[cn]
                  names = items[0]
                  maxid = 1
                  for itemprops in items[1:]:
                      id = int(klass.import_list(names, itemprops))
                      if hasattr(klass, 'import_files'):
                          klass.import_files('_test_export', str(id))
                      maxid = max(maxid, id)
                  self.db.setid(cn, str(maxid+1))
                  klass.import_journals(journals[cn])

            if self.db.dbtype not in ['anydbm', 'memorydb']:
                # no logs or fixup needed under anydbm
                # postgres requires commits and rollbacks
                # as part of error recovery, so we get commit
                # logging that we need to account for
                log = []
                if self.db.dbtype == 'postgres':
                    # remove commit and rollback log messages
                    # so the indexes below work correctly.
                    for i in range(0,len(self._caplog.record_tuples)):
                        if self._caplog.record_tuples[i][2] not in \
                           ["commit", "rollback"]:
                            log.append(self._caplog.record_tuples[i])
                else:
                    log = self._caplog.record_tuples[:]

                log_count=2
                handle_msg_location=0
                success_msg_location = handle_msg_location+1

                self.assertEqual(log_count, len(log))
                self.assertIn('Attempting to handle import exception for id 7:',
                              log[handle_msg_location][2])
                self.assertIn('Successfully handled import exception for id 7 '
                              'which conflicted with 6',
                              log[success_msg_location][2])

            # This is needed, otherwise journals won't be there for anydbm
            self.db.commit()
        finally:
            shutil.rmtree('_test_export')

        # compare with snapshot of the database
        for cn, items in orig.items():
            klass = self.db.classes[cn]
            propdefs = klass.getprops(1)
            # ensure retired items are retired :)
            l = sorted(items.keys())
            m = klass.list(); m.sort()
            ae(l, m, '%s id list wrong %r vs. %r'%(cn, l, m))
            for id, props in items.items():
                for name, value in props.items():
                    l = klass.get(id, name)
                    if isinstance(value, type([])):
                        value.sort()
                        l.sort()
                    try:
                        ae(l, value)
                    except AssertionError:
                        if not isinstance(propdefs[name], Date):
                            raise
                        # don't get hung up on rounding errors
                        assert not l.__cmp__(value, int_seconds=1)
        for jc, items in origj.items():
            for id, oj in items.items():
                rj = self.db.getjournal(jc, id)
                # Both mysql and postgresql have some minor issues with
                # rounded seconds on export/import, so we compare only
                # the integer part.
                for j in oj:
                    j[1].second = float(int(j[1].second))
                for j in rj:
                    j[1].second = float(int(j[1].second))
                oj.sort(key = NoneAndDictComparable)
                rj.sort(key = NoneAndDictComparable)
                ae(oj, rj)

        # make sure the retired items are actually imported
        ae(self.db.user.get('4', 'username'), 'blop')
        ae(self.db.issue.get('2', 'title'), 'issue two')

        # make sure id counters are set correctly
        maxid = max([int(id) for id in self.db.user.list()])
        newid = int(self.db.user.create(username='testing'))
        self.assertGreater(newid, maxid)

    # test import/export via admin interface
    def testAdminImportExport(self):
        import roundup.admin
        import csv
        # use the filtering setup to create a bunch of items
        ae, dummy = self.filteringSetup()
        # create large field
        self.db.priority.create(name = 'X' * 500)
        self.db.config.CSV_FIELD_SIZE = 400
        self.db.commit()
        output = []
        # ugly hack to get stderr output and disable stdout output
        # during regression test. Depends on roundup.admin not using
        # anything but stdout/stderr from sys (which is currently the
        # case)
        def stderrwrite(s):
            output.append(s)
        roundup.admin.sys = MockNull ()
        try:
            roundup.admin.sys.stderr.write = stderrwrite
            tool = roundup.admin.AdminTool()
            home = '.'
            tool.tracker_home = home
            tool.db = self.db
            tool.verbose = False
            tool.do_export (['_test_export'])
            self.assertEqual(len(output), 2)
            self.assertEqual(output [1], '\n')
            self.assertTrue(output [0].startswith
                ('Warning: config csv_field_size should be at least'))
            self.assertTrue(int(output[0].split()[-1]) > 500)

            if hasattr(roundup.admin.csv, 'field_size_limit'):
                self.nukeAndCreate()
                self.db.config.CSV_FIELD_SIZE = 400
                tool = roundup.admin.AdminTool()
                tool.tracker_home = home
                tool.db = self.db
                tool.verbose = False
                self.assertRaises(csv.Error, tool.do_import, ['_test_export'])

            self.nukeAndCreate()
            self.db.config.CSV_FIELD_SIZE = 3200
            tool = roundup.admin.AdminTool()
            tool.tracker_home = home
            tool.db = self.db
            tool.verbose = False
            tool.do_import(['_test_export'])
        finally:
            roundup.admin.sys = sys
            shutil.rmtree('_test_export')

    # test props from args parsing
    def testAdminOtherCommands(self):
        import roundup.admin

        # use the filtering setup to create a bunch of items
        ae, dummy = self.filteringSetup()
        # create large field
        self.db.priority.create(name = 'X' * 500)
        self.db.config.CSV_FIELD_SIZE = 400
        self.db.commit()

        eoutput = [] # stderr output
        soutput = [] # stdout output

        def stderrwrite(s):
            eoutput.append(s)
        def stdoutwrite(s):
            soutput.append(s)
        roundup.admin.sys = MockNull ()
        try:
            roundup.admin.sys.stderr.write = stderrwrite
            roundup.admin.sys.stdout.write = stdoutwrite

            tool = roundup.admin.AdminTool()
            home = '.'
            tool.tracker_home = home
            tool.db = self.db
            tool.verbose = False
            tool.separator = "\n"
            tool.print_designator = True

            # test props_from_args
            self.assertRaises(UsageError, tool.props_from_args, "fullname") # invalid propname

            self.assertEqual(tool.props_from_args("="), {'': None}) # not sure this desired, I'd expect UsageError

            props = tool.props_from_args(["fullname=robert", "friends=+rouilj,+other", "key="])
            self.assertEqual(props, {'fullname': 'robert', 'friends': '+rouilj,+other', 'key': None})

            # test get_class()
            self.assertRaises(UsageError, tool.get_class, "bar") # invalid class

            # This writes to stdout, need to figure out how to redirect to a variable.
            # classhandle = tool.get_class("user") # valid class
            # FIXME there should be some test here

            issue_class_spec = tool.do_specification(["issue"])
            self.assertEqual(sorted (soutput),
                     ['assignedto: <roundup.hyperdb.Link to "user">\n',
                      'deadline: <roundup.hyperdb.Date>\n',
                      'feedback: <roundup.hyperdb.Link to "msg">\n',
                      'files: <roundup.hyperdb.Multilink to "file">\n',
                      'foo: <roundup.hyperdb.Interval>\n',
                      'keywords2: <roundup.hyperdb.Multilink to "keyword">\n',
                      'keywords: <roundup.hyperdb.Multilink to "keyword">\n',
                      'messages: <roundup.hyperdb.Multilink to "msg">\n',
                      'nosy: <roundup.hyperdb.Multilink to "user">\n',
                      'priority: <roundup.hyperdb.Link to "priority">\n',
                      'spam: <roundup.hyperdb.Multilink to "msg">\n',
                      'status: <roundup.hyperdb.Link to "status">\n',
                      'superseder: <roundup.hyperdb.Multilink to "issue">\n',
                      'title: <roundup.hyperdb.String>\n'])

            #userclassprop=tool.do_list(["mls"])
            #tool.print_designator = False
            #userclassprop=tool.do_get(["realname","user1"])

            # test do_create
            soutput[:] = [] # empty for next round of output
            userclass=tool.do_create(["issue", "title='title1 title'", "nosy=1,3"]) # should be issue 5
            userclass=tool.do_create(["issue", "title='title2 title'", "nosy=2,3"]) # should be issue 6
            self.assertEqual(soutput, ['5\n', '6\n'])
            # verify nosy setting
            props=self.db.issue.get('5', "nosy")
            self.assertEqual(props, ['1','3'])

            # test do_set using newly created issues
            # remove user 3 from issues
            # verifies issue2550572
            userclass=tool.do_set(["issue5,issue6", "nosy=-3"])
            # verify proper result
            props=self.db.issue.get('5', "nosy")
            self.assertEqual(props, ['1'])
            props=self.db.issue.get('6', "nosy")
            self.assertEqual(props, ['2'])

            # basic usage test. TODO add full output verification
            soutput[:] = [] # empty for next round of output
            tool.usage(message="Hello World")
            self.assertTrue(soutput[0].startswith('Problem: Hello World'), None)

            # check security output
            soutput[:] = [] # empty for next round of output
            tool.do_security("Admin")
            expected =  [ 'New Web users get the Role "User"\n',
                          'New Email users get the Role "User"\n',
                          'Role "admin":\n',
                          ' User may create everything (Create)\n',
                          ' User may edit everything (Edit)\n',
                          ' User may restore everything (Restore)\n',
                          ' User may retire everything (Retire)\n',
                          ' User may view everything (View)\n',
                          ' User may access the web interface (Web Access)\n',
                          ' User may access the rest interface (Rest Access)\n',
                          ' User may access the xmlrpc interface (Xmlrpc Access)\n',
                          ' User may manipulate user Roles through the web (Web Roles)\n',
                          ' User may use the email interface (Email Access)\n',
                          'Role "anonymous":\n', 'Role "user":\n',
                          ' User is allowed to access msg (View for "msg" only)\n',
                          ' Prevent users from seeing roles (View for "user": [\'username\', \'supervisor\', \'assignable\'] only)\n']

            self.assertEqual(soutput, expected)


            self.nukeAndCreate()
            tool = roundup.admin.AdminTool()
            tool.tracker_home = home
            tool.db = self.db
            tool.verbose = False
        finally:
            roundup.admin.sys = sys


    # test duplicate relative tracker home initialisation (issue2550757)
    def testAdminDuplicateInitialisation(self):
        import roundup.admin
        output = []
        def stderrwrite(s):
            output.append(s)
        roundup.admin.sys = MockNull ()
        t = '_test_initialise'
        try:
            roundup.admin.sys.stderr.write = stderrwrite
            tool = roundup.admin.AdminTool()
            tool.force = True
            args = (None, 'classic', 'anydbm',
                    'MAIL_DOMAIN=%s' % config.MAIL_DOMAIN)
            tool.do_install(t, args=args)
            args = (None, 'mypasswd')
            tool.do_initialise(t, args=args)
            tool.do_initialise(t, args=args)
            try:  # python >=2.7
                self.assertNotIn(t, os.listdir(t))
            except AttributeError:
                self.assertFalse('db' in os.listdir(t))
        finally:
            roundup.admin.sys = sys
            if os.path.exists(t):
                shutil.rmtree(t)

    def testAddProperty(self):
        self.db.issue.create(title="spam", status='1')
        self.db.commit()

        self.db.issue.addprop(fixer=Link("user"))
        # force any post-init stuff to happen
        self.db.post_init()
        props = self.db.issue.getprops()
        keys = sorted(props.keys())
        self.assertEqual(keys, ['activity', 'actor', 'assignedto', 'creation',
            'creator', 'deadline', 'feedback', 'files', 'fixer', 'foo',
            'id', 'keywords', 'keywords2', 'messages', 'nosy', 'priority',
            'spam', 'status', 'superseder', 'title'])
        self.assertEqual(self.db.issue.get('1', "fixer"), None)

    def testRemoveProperty(self):
        self.db.issue.create(title="spam", status='1')
        self.db.commit()

        del self.db.issue.properties['title']
        self.db.post_init()
        props = self.db.issue.getprops()
        keys = sorted(props.keys())
        self.assertEqual(keys, ['activity', 'actor', 'assignedto', 'creation',
            'creator', 'deadline', 'feedback', 'files', 'foo', 'id',
            'keywords', 'keywords2', 'messages', 'nosy', 'priority', 'spam',
            'status', 'superseder'])
        self.assertEqual(self.db.issue.list(), ['1'])

    def testAddRemoveProperty(self):
        self.db.issue.create(title="spam", status='1')
        self.db.commit()

        self.db.issue.addprop(fixer=Link("user"))
        del self.db.issue.properties['title']
        self.db.post_init()
        props = self.db.issue.getprops()
        keys = sorted(props.keys())
        self.assertEqual(keys, ['activity', 'actor', 'assignedto', 'creation',
            'creator', 'deadline', 'feedback', 'files', 'fixer', 'foo', 'id',
            'keywords', 'keywords2', 'messages', 'nosy', 'priority', 'spam',
            'status', 'superseder'])
        self.assertEqual(self.db.issue.list(), ['1'])

    def testNosyMail(self) :
        """Creates one issue with two attachments, one smaller and one larger
           than the set max_attachment_size.
        """
        old_translate_ = roundupdb._
        roundupdb._ = i18n.get_translation(language='C').gettext
        db = self.db
        db.config.NOSY_MAX_ATTACHMENT_SIZE = 4096
        res = dict(mail_to = None, mail_msg = None)
        def dummy_snd(s, to, msg, res=res) :
            res["mail_to"], res["mail_msg"] = to, msg
        backup, Mailer.smtp_send = Mailer.smtp_send, dummy_snd
        try :
            f1 = db.file.create(name="test1.txt", content="x" * 20, type="application/octet-stream")
            f2 = db.file.create(name="test2.txt", content="y" * 5000, type="application/octet-stream")
            m  = db.msg.create(content="one two", author="admin",
                files = [f1, f2])
            i  = db.issue.create(title='spam', files = [f1, f2],
                messages = [m], nosy = [db.user.lookup("fred")])

            db.issue.nosymessage(i, m, {})
            mail_msg = str(res["mail_msg"])
            self.assertEqual(res["mail_to"], ["fred@example.com"])
            self.assertTrue("From: admin" in mail_msg)
            self.assertTrue("Subject: [issue1] spam" in mail_msg)
            self.assertTrue("New submission from admin" in mail_msg)
            self.assertTrue("one two" in mail_msg)
            self.assertTrue("File 'test1.txt' not attached" not in mail_msg)
            self.assertTrue(b2s(base64_encode(s2b("xxx"))).rstrip() in mail_msg)
            self.assertTrue("File 'test2.txt' not attached" in mail_msg)
            self.assertTrue(b2s(base64_encode(s2b("yyy"))).rstrip() not in mail_msg)
        finally :
            roundupdb._ = old_translate_
            Mailer.smtp_send = backup

    def testNosyMailTextAndBinary(self) :
        """Creates one issue with two attachments, one as text and one as binary.
        """
        old_translate_ = roundupdb._
        roundupdb._ = i18n.get_translation(language='C').gettext
        db = self.db
        res = dict(mail_to = None, mail_msg = None)
        def dummy_snd(s, to, msg, res=res) :
            res["mail_to"], res["mail_msg"] = to, msg
        backup, Mailer.smtp_send = Mailer.smtp_send, dummy_snd
        try :
            f1 = db.file.create(name="test1.txt", content="Hello world", type="text/plain")
            f2 = db.file.create(name="test2.bin", content=b"\x01\x02\x03\xfe\xff", type="application/octet-stream")
            m  = db.msg.create(content="one two", author="admin",
                files = [f1, f2])
            i  = db.issue.create(title='spam', files = [f1, f2],
                messages = [m], nosy = [db.user.lookup("fred")])

            db.issue.nosymessage(i, m, {})
            mail_msg = str(res["mail_msg"])
            self.assertEqual(res["mail_to"], ["fred@example.com"])
            self.assertTrue("From: admin" in mail_msg)
            self.assertTrue("Subject: [issue1] spam" in mail_msg)
            self.assertTrue("New submission from admin" in mail_msg)
            self.assertTrue("one two" in mail_msg)
            self.assertTrue("Hello world" in mail_msg)
            self.assertTrue(b2s(base64_encode(b"\x01\x02\x03\xfe\xff")).rstrip() in mail_msg)
        finally :
            roundupdb._ = old_translate_
            Mailer.smtp_send = backup

    @pytest.mark.skipif(gpgmelib.gpg is None, reason='Skipping PGPNosy test')
    def testPGPNosyMail(self) :
        """Creates one issue with two attachments, one smaller and one larger
           than the set max_attachment_size. Recipients are one with and
           one without encryption enabled via a gpg group.
        """
        old_translate_ = roundupdb._
        roundupdb._ = i18n.get_translation(language='C').gettext
        db = self.db
        db.config.NOSY_MAX_ATTACHMENT_SIZE = 4096
        db.config['PGP_HOMEDIR'] = gpgmelib.pgphome
        db.config['PGP_ROLES'] = 'pgp'
        db.config['PGP_ENABLE'] = True
        db.config['PGP_ENCRYPT'] = True
        gpgmelib.setUpPGP()
        res = []
        def dummy_snd(s, to, msg, res=res) :
            res.append (dict (mail_to = to, mail_msg = msg))
        backup, Mailer.smtp_send = Mailer.smtp_send, dummy_snd
        try :
            john = db.user.create(username="john", roles='User,pgp',
                address='john@test.test', realname='John Doe')
            f1 = db.file.create(name="test1.txt", content="x" * 20, type="application/octet-stream")
            f2 = db.file.create(name="test2.txt", content="y" * 5000, type="application/octet-stream")
            m  = db.msg.create(content="one two", author="admin",
                files = [f1, f2])
            i  = db.issue.create(title='spam', files = [f1, f2],
                messages = [m], nosy = [db.user.lookup("fred"), john])

            db.issue.nosymessage(i, m, {})
            res.sort(key=lambda x: x['mail_to'])
            self.assertEqual(res[0]["mail_to"], ["fred@example.com"])
            self.assertEqual(res[1]["mail_to"], ["john@test.test"])
            mail_msg = str(res[0]["mail_msg"])
            self.assertTrue("From: admin" in mail_msg)
            self.assertTrue("Subject: [issue1] spam" in mail_msg)
            self.assertTrue("New submission from admin" in mail_msg)
            self.assertTrue("one two" in mail_msg)
            self.assertTrue("File 'test1.txt' not attached" not in mail_msg)
            self.assertTrue(b2s(base64_encode(s2b("xxx"))).rstrip() in mail_msg)
            self.assertTrue("File 'test2.txt' not attached" in mail_msg)
            self.assertTrue(b2s(base64_encode(s2b("yyy"))).rstrip() not in mail_msg)
            mail_msg = str(res[1]["mail_msg"])
            parts = message_from_string(mail_msg).get_payload()
            self.assertEqual(len(parts),2)
            self.assertEqual(parts[0].get_payload().strip(), 'Version: 1')
            crypt = gpgmelib.gpg.core.Data(parts[1].get_payload())
            plain = gpgmelib.gpg.core.Data()
            ctx = gpgmelib.gpg.core.Context()
            res = ctx.op_decrypt(crypt, plain)
            self.assertEqual(res, None)
            plain.seek(0,0)
            self.assertTrue("From: admin" in mail_msg)
            self.assertTrue("Subject: [issue1] spam" in mail_msg)
            mail_msg = str(message_from_bytes(plain.read()))
            self.assertTrue("New submission from admin" in mail_msg)
            self.assertTrue("one two" in mail_msg)
            self.assertTrue("File 'test1.txt' not attached" not in mail_msg)
            self.assertTrue(b2s(base64_encode(s2b("xxx"))).rstrip() in mail_msg)
            self.assertTrue("File 'test2.txt' not attached" in mail_msg)
            self.assertTrue(b2s(base64_encode(s2b("yyy"))).rstrip() not in mail_msg)
        finally :
            roundupdb._ = old_translate_
            Mailer.smtp_send = backup
            gpgmelib.tearDownPGP()

class ROTest(MyTestCase):
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = self.module.Database(config, 'admin')
        setupSchema(self.db, 1, self.module)
        self.db.close()

        self.db = self.module.Database(config)
        setupSchema(self.db, 0, self.module)

    def testExceptions(self):
        # this tests the exceptions that should be raised
        ar = self.assertRaises

        # this tests the exceptions that should be raised
        ar(DatabaseError, self.db.status.create, name="foo")
        ar(DatabaseError, self.db.status.set, '1', name="foo")
        ar(DatabaseError, self.db.status.retire, '1')


class SchemaTest(MyTestCase):
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')

    def test_reservedProperties(self):
        self.open_database()
        self.assertRaises(ValueError, self.module.Class, self.db, "a",
            creation=String())
        self.assertRaises(ValueError, self.module.Class, self.db, "a",
            activity=String())
        self.assertRaises(ValueError, self.module.Class, self.db, "a",
            creator=String())
        self.assertRaises(ValueError, self.module.Class, self.db, "a",
            actor=String())

    def init_a(self):
        self.open_database()
        a = self.module.Class(self.db, "a", name=String())
        a.setkey("name")
        self.db.post_init()

    def test_fileClassProps(self):
        self.open_database()
        a = self.module.FileClass(self.db, 'a')
        l = sorted(a.getprops().keys())
        self.assertTrue(l, ['activity', 'actor', 'content', 'created',
            'creation', 'type'])

    def init_ab(self):
        self.open_database()
        a = self.module.Class(self.db, "a", name=String())
        a.setkey("name")
        b = self.module.Class(self.db, "b", name=String(),
            fooz=Multilink('a'))
        b.setkey("name")
        self.db.post_init()

    def test_splitDesignator(self):
        from roundup.hyperdb import splitDesignator, DesignatorError

        self.open_database() # allow setup/shutdown to work to postgres/mysql

        valid_test_cases = [('zip2py44', ('zip2py', '44')),
                              ('zippy2', ('zippy', '2')),
                              ('a9', ('a', '9')),
                              ('a1234', ('a', '1234')),
                              ('a_1234', ('a_', '1234')),
        ]

        invalid_test_cases = ['_zip2py44','1zippy44',
                              'zippy244a' ]

        for designator in valid_test_cases:
            print("Testing %s"%designator[0])
            self.assertEqual(splitDesignator(designator[0]), designator[1])

        for designator in invalid_test_cases:
            print("Testing %s"%designator)
            with self.assertRaises(DesignatorError) as ctx:
                splitDesignator(designator)
            error = '"%s" not a node designator' % designator
            self.assertEqual(str(ctx.exception), error)


    def test_addNewClass(self):
        self.init_a()

        with self.assertRaises(ValueError) as ctx:
            self.module.Class(self.db, "a", name=String())
        error = 'Class "a" already defined.'
        self.assertEqual(str(ctx.exception), error)

        aid = self.db.a.create(name='apple')
        self.db.commit(); self.db.close()

        # Test permutations of valid/invalid classnames
        self.init_a()

        for classname in [ "1badclassname", "badclassname1",
                           "_badclassname", "_", "5" ]:
            print("testing %s\n" % classname)
            with self.assertRaises(ValueError) as ctx:
                self.module.Class(self.db, classname, name=String())

            error = ('Class name %s is not valid. It must start '
                     'with a letter, end with a letter or "_", and '
                     'only have alphanumerics and "_" in the middle.' % (classname,))
            self.assertEqual(str(ctx.exception), error)

        for classname in [ 'cla2ss', 'c_lass', 'CL_2ass', 'Z',
                            'class2_' ]:
            print("testing %s\n" % classname)
            c = self.module.Class(self.db, classname, name=String())
            self.assertEqual(str(c), '<hyperdb.Class "%s">' % classname)

        # don't pollute the db with junk valid cases
        # self.db.commit(); close to discard all changes in this block.
        self.db.close()

        # add a new class to the schema and check creation of new items
        # (and existence of old ones)
        self.init_ab()
        bid = self.db.b.create(name='bear', fooz=[aid])
        self.assertEqual(self.db.a.get(aid, 'name'), 'apple')
        self.db.commit()
        self.db.close()

        # now check we can recall the added class' items
        self.init_ab()
        self.assertEqual(self.db.a.get(aid, 'name'), 'apple')
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.assertEqual(self.db.b.get(bid, 'name'), 'bear')
        self.assertEqual(self.db.b.get(bid, 'fooz'), [aid])
        self.assertEqual(self.db.b.lookup('bear'), bid)

        # confirm journal's ok
        self.db.getjournal('a', aid)
        self.db.getjournal('b', bid)

    def init_amod(self):
        self.open_database()
        a = self.module.Class(self.db, "a", name=String(), newstr=String(),
            newint=Interval(), newnum=Number(), newbool=Boolean(),
            newdate=Date())
        a.setkey("name")
        b = self.module.Class(self.db, "b", name=String())
        b.setkey("name")
        self.db.post_init()

    def test_modifyClass(self):
        self.init_ab()

        # add item to user and issue class
        aid = self.db.a.create(name='apple')
        bid = self.db.b.create(name='bear')
        self.db.commit(); self.db.close()

        # modify "a" schema
        self.init_amod()
        self.assertEqual(self.db.a.get(aid, 'name'), 'apple')
        self.assertEqual(self.db.a.get(aid, 'newstr'), None)
        self.assertEqual(self.db.a.get(aid, 'newint'), None)
        # hack - metakit can't return None for missing values, and we're not
        # really checking for that behavior here anyway
        self.assertTrue(not self.db.a.get(aid, 'newnum'))
        self.assertTrue(not self.db.a.get(aid, 'newbool'))
        self.assertEqual(self.db.a.get(aid, 'newdate'), None)
        self.assertEqual(self.db.b.get(aid, 'name'), 'bear')
        aid2 = self.db.a.create(name='aardvark', newstr='booz')
        self.db.commit(); self.db.close()

        # test
        self.init_amod()
        self.assertEqual(self.db.a.get(aid, 'name'), 'apple')
        self.assertEqual(self.db.a.get(aid, 'newstr'), None)
        self.assertEqual(self.db.b.get(aid, 'name'), 'bear')
        self.assertEqual(self.db.a.get(aid2, 'name'), 'aardvark')
        self.assertEqual(self.db.a.get(aid2, 'newstr'), 'booz')

        # confirm journal's ok
        self.db.getjournal('a', aid)
        self.db.getjournal('a', aid2)

    def init_amodkey(self):
        self.open_database()
        a = self.module.Class(self.db, "a", name=String(), newstr=String())
        a.setkey("newstr")
        b = self.module.Class(self.db, "b", name=String())
        b.setkey("name")
        self.db.post_init()

    def test_changeClassKey(self):
        self.init_amod()
        aid = self.db.a.create(name='apple')
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.db.commit(); self.db.close()

        # change the key to newstr on a
        self.init_amodkey()
        self.assertEqual(self.db.a.get(aid, 'name'), 'apple')
        self.assertEqual(self.db.a.get(aid, 'newstr'), None)
        self.assertRaises(KeyError, self.db.a.lookup, 'apple')
        aid2 = self.db.a.create(name='aardvark', newstr='booz')
        self.db.commit(); self.db.close()

        # check
        self.init_amodkey()
        self.assertEqual(self.db.a.lookup('booz'), aid2)

        # confirm journal's ok
        self.db.getjournal('a', aid)

    def test_removeClassKey(self):
        self.init_amod()
        aid = self.db.a.create(name='apple')
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.db.commit(); self.db.close()

        self.db = self.module.Database(config, 'admin')
        a = self.module.Class(self.db, "a", name=String(), newstr=String())
        self.db.post_init()

        aid2 = self.db.a.create(name='apple', newstr='booz')
        self.db.commit()


    def init_amodml(self):
        self.open_database()
        a = self.module.Class(self.db, "a", name=String(),
            newml=Multilink('a'))
        a.setkey('name')
        self.db.post_init()

    def test_makeNewMultilink(self):
        self.init_a()
        aid = self.db.a.create(name='apple')
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.db.commit(); self.db.close()

        # add a multilink prop
        self.init_amodml()
        bid = self.db.a.create(name='bear', newml=[aid])
        self.assertEqual(self.db.a.find(newml=aid), [bid])
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.db.commit(); self.db.close()

        # check
        self.init_amodml()
        self.assertEqual(self.db.a.find(newml=aid), [bid])
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.assertEqual(self.db.a.lookup('bear'), bid)

        # confirm journal's ok
        self.db.getjournal('a', aid)
        self.db.getjournal('a', bid)

    def test_removeMultilink(self):
        # add a multilink prop
        self.init_amodml()
        aid = self.db.a.create(name='apple')
        bid = self.db.a.create(name='bear', newml=[aid])
        self.assertEqual(self.db.a.find(newml=aid), [bid])
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.assertEqual(self.db.a.lookup('bear'), bid)
        self.db.commit(); self.db.close()

        # remove the multilink
        self.init_a()
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.assertEqual(self.db.a.lookup('bear'), bid)

        # confirm journal's ok
        self.db.getjournal('a', aid)
        self.db.getjournal('a', bid)

    def test_removeClass(self):
        self.init_ab()
        aid = self.db.a.create(name='apple')
        bid = self.db.b.create(name='bear')
        self.db.commit(); self.db.close()

        # drop the b class
        self.init_a()
        self.assertEqual(self.db.a.get(aid, 'name'), 'apple')
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.db.commit(); self.db.close()

        # now check we can recall the added class' items
        self.init_a()
        self.assertEqual(self.db.a.get(aid, 'name'), 'apple')
        self.assertEqual(self.db.a.lookup('apple'), aid)

        # confirm journal's ok
        self.db.getjournal('a', aid)

class RDBMSTest:
    """ tests specific to RDBMS backends """
    def test_indexTest(self):
        self.assertEqual(self.db.sql_index_exists('_issue', '_issue_id_idx'), 1)
        self.assertEqual(self.db.sql_index_exists('_issue', '_issue_x_idx'), 0)

class FilterCacheTest(commonDBTest):
    def testFilteringTransitiveLinkCache(self):
        ae, dummy = self.filteringSetupTransitiveSearch()
        ae, dummy = self.iterSetup('user')
        # Need to make ceo his own (and first two users') supervisor
        self.db.user.set('1', supervisor = '3')
        self.db.user.set('2', supervisor = '3')
        self.db.user.set('3', supervisor = '3')
        # test bool value
        self.db.user.set('4', assignable = True)
        self.db.user.set('3', assignable = False)
        filt = self.db.issue.filter_iter
        ufilt = self.db.user.filter_iter
        user_result = \
            {  '1' : {'username': 'admin', 'assignable': None,
                      'supervisor': '3', 'realname': None, 'roles': 'Admin',
                      'creator': '1', 'age': None, 'actor': '1',
                      'address': None}
            ,  '2' : {'username': 'fred', 'assignable': None,
                      'supervisor': '3', 'realname': None, 'roles': 'User',
                      'creator': '1', 'age': None, 'actor': '1',
                      'address': 'fred@example.com'}
            ,  '3' : {'username': 'ceo', 'assignable': False,
                      'supervisor': '3', 'realname': None, 'roles': None,
                      'creator': '1', 'age': 129.0, 'actor': '1',
                      'address': None}
            ,  '4' : {'username': 'grouplead1', 'assignable': True,
                      'supervisor': '3', 'realname': None, 'roles': None,
                      'creator': '1', 'age': 29.0, 'actor': '1',
                      'address': None}
            ,  '5' : {'username': 'grouplead2', 'assignable': None,
                      'supervisor': '3', 'realname': None, 'roles': None,
                      'creator': '1', 'age': 29.0, 'actor': '1',
                      'address': None}
            ,  '6' : {'username': 'worker1', 'assignable': None,
                      'supervisor': '4', 'realname': None, 'roles': None,
                      'creator': '1', 'age': 25.0, 'actor': '1',
                      'address': None}
            ,  '7' : {'username': 'worker2', 'assignable': None,
                      'supervisor': '4', 'realname': None, 'roles': None,
                      'creator': '1', 'age': 24.0, 'actor': '1',
                      'address': None}
            ,  '8' : {'username': 'worker3', 'assignable': None,
                      'supervisor': '5', 'realname': None, 'roles': None,
                      'creator': '1', 'age': 23.0, 'actor': '1',
                      'address': None}
            ,  '9' : {'username': 'worker4', 'assignable': None,
                      'supervisor': '5', 'realname': None, 'roles': None,
                      'creator': '1', 'age': 22.0, 'actor': '1',
                      'address': None}
            , '10' : {'username': 'worker5', 'assignable': None,
                      'supervisor': '5', 'realname': None, 'roles': None,
                      'creator': '1', 'age': 21.0, 'actor': '1',
                      'address': None}
            }
        foo = date.Interval('-1d')
        issue_result = \
            { '1' : {'title': 'ts1', 'status': '2', 'assignedto': '6',
                     'priority': '3', 'messages' : ['4'], 'nosy' : ['4']}
            , '2' : {'title': 'ts2', 'status': '1', 'assignedto': '6',
                     'priority': '3', 'messages' : ['4'], 'nosy' : ['5']}
            , '3' : {'title': 'ts4', 'status': '2', 'assignedto': '7',
                     'priority': '3', 'messages' : ['5']}
            , '4' : {'title': 'ts5', 'status': '1', 'assignedto': '8',
                     'priority': '3', 'messages' : ['6']}
            , '5' : {'title': 'ts6', 'status': '2', 'assignedto': '9',
                     'priority': '3', 'messages' : ['7']}
            , '6' : {'title': 'ts7', 'status': '1', 'assignedto': '10',
                     'priority': '3', 'messages' : ['8'], 'foo' : None}
            , '7' : {'title': 'ts8', 'status': '2', 'assignedto': '10',
                     'priority': '3', 'messages' : ['8'], 'foo' : foo}
            , '8' : {'title': 'ts9', 'status': '1', 'assignedto': '10',
                     'priority': '3', 'messages' : ['7', '8']}
            }
        result = []
        self.db.clearCache()
        for id in ufilt(None, {}, [('+','supervisor.supervisor.supervisor'),
            ('-','supervisor.supervisor'), ('-','supervisor'),
            ('+','username')]):
            result.append(id)
            nodeid = id
            # Note in the recent implementation we do not recursively
            # cache results in filter_iter
            assert(('user', nodeid) in self.db.cache)
            n = self.db.user.getnode(nodeid)
            for k, v in user_result[nodeid].items():
                ae((k, n[k]), (k, v))
            for k in 'creation', 'activity':
                assert(n[k])
            self.db.clearCache()
        ae (result, ['8', '9', '10', '6', '7', '1', '3', '2', '4', '5'])

        result = []
        self.db.clearCache()
        for id in filt(None, {},
            [('+','assignedto.supervisor.supervisor.supervisor'),
            ('+','assignedto.supervisor.supervisor'),
            ('-','assignedto.supervisor'), ('+','assignedto')]):
            result.append(id)
            assert(('issue', id) in self.db.cache)
            n = self.db.issue.getnode(id)
            for k, v in issue_result[id].items():
                ae((k, n[k]), (k, v))
            for k in 'creation', 'activity':
                assert(n[k])
            nodeid = n.assignedto
            # Note in the recent implementation we do not recursively
            # cache results in filter_iter
            n = self.db.user.getnode(nodeid)
            for k, v in user_result[nodeid].items():
                ae((k, n[k]), (k, v))
            for k in 'creation', 'activity':
                assert(n[k])
            self.db.clearCache()
        ae (result, ['4', '5', '6', '7', '8', '1', '2', '3'])


class ClassicInitBase(object):
    count = 0
    db = None

    def setUp(self):
        ClassicInitBase.count = ClassicInitBase.count + 1
        self.dirname = '_test_init_%s'%self.count
        try:
            shutil.rmtree(self.dirname)
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def tearDown(self):
        if self.db is not None:
            self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

class ClassicInitTest(ClassicInitBase):
    def testCreation(self):
        ae = self.assertEqual

        # set up and open a tracker
        tracker = setupTracker(self.dirname, self.backend)
        # open the database
        db = self.db = tracker.open('test')

        # check the basics of the schema and initial data set
        l = db.priority.list()
        l.sort()
        ae(l, ['1', '2', '3', '4', '5'])
        l = db.status.list()
        l.sort()
        ae(l, ['1', '2', '3', '4', '5', '6', '7', '8'])
        l = db.keyword.list()
        ae(l, [])
        l = db.user.list()
        l.sort()
        ae(l, ['1', '2'])
        l = db.msg.list()
        ae(l, [])
        l = db.file.list()
        ae(l, [])
        l = db.issue.list()
        ae(l, [])


class ConcurrentDBTest(ClassicInitBase):
    def testConcurrency(self):
        # The idea here is a read-modify-update cycle in the presence of
        # a cache that has to be properly handled. The same applies if
        # we extend a String or otherwise modify something that depends
        # on the previous value.

        # set up and open a tracker
        tracker = setupTracker(self.dirname, self.backend)
        # open the database
        self.db = tracker.open('admin')

        prio = '1'
        self.assertEqual(self.db.priority.get(prio, 'order'), 1.0)
        def inc(db):
            db.priority.set(prio, order=db.priority.get(prio, 'order') + 1)

        inc(self.db)

        db2 = tracker.open("admin")
        self.assertEqual(db2.priority.get(prio, 'order'), 1.0)
        db2.commit()
        self.db.commit()
        self.assertEqual(self.db.priority.get(prio, 'order'), 2.0)

        inc(db2)
        db2.commit()
        db2.clearCache()
        self.assertEqual(db2.priority.get(prio, 'order'), 3.0)
        db2.close()

class HTMLItemTest(ClassicInitBase):
    class Request :
        """ Fake html request """
        rfile = None
        def start_response (self, a, b) :
            pass
        # end def start_response
    # end class Request

    def setUp(self):
        super(HTMLItemTest, self).setUp()
        self.tracker = tracker = setupTracker(self.dirname, self.backend)
        db = self.db = tracker.open('admin')
        req = self.Request()
        env = dict (PATH_INFO='', REQUEST_METHOD='GET', QUERY_STRING='')
        self.client = self.tracker.Client(self.tracker, req, env, None)
        self.client.db = db
        self.client.language = None
        self.client.userid = db.getuid()
        self.client.classname = 'issue'
        user = {'username': 'worker5', 'realname': 'Worker', 'roles': 'User'}
        u = self.db.user.create(**user)
        u_m = self.db.msg.create(author = u, content = 'bla'
            , date = date.Date ('2006-01-01'))
        issue = {'title': 'ts1', 'status': '2', 'assignedto': '3',
                'priority': '3', 'messages' : [u_m], 'nosy' : ['3']}
        self.db.issue.create(**issue)
        issue = {'title': 'ts2', 'status': '2',
                'messages' : [u_m], 'nosy' : ['3']}
        self.db.issue.create(**issue)

    def testHTMLItemAttributes(self):
        issue = HTMLItem(self.client, 'issue', '1')
        ae = self.assertEqual
        ae(issue.title.plain(),'ts1')
        ae(issue ['title'].plain(),'ts1')
        ae(issue.status.plain(),'deferred')
        ae(issue ['status'].plain(),'deferred')
        ae(issue.assignedto.plain(),'worker5')
        ae(issue ['assignedto'].plain(),'worker5')
        ae(issue.priority.plain(),'bug')
        ae(issue ['priority'].plain(),'bug')
        ae(issue.messages.plain(),'1')
        ae(issue ['messages'].plain(),'1')
        ae(issue.nosy.plain(),'worker5')
        ae(issue ['nosy'].plain(),'worker5')
        ae(len(issue.messages),1)
        ae(len(issue ['messages']),1)
        ae(len(issue.nosy),1)
        ae(len(issue ['nosy']),1)

    def testHTMLItemDereference(self):
        issue = HTMLItem(self.client, 'issue', '1')
        ae = self.assertEqual
        ae(str(issue.priority.name),'bug')
        ae(str(issue.priority['name']),'bug')
        ae(str(issue ['priority']['name']),'bug')
        ae(str(issue ['priority'].name),'bug')
        ae(str(issue.assignedto.username),'worker5')
        ae(str(issue.assignedto['username']),'worker5')
        ae(str(issue ['assignedto']['username']),'worker5')
        ae(str(issue ['assignedto'].username),'worker5')
        for n in issue.nosy:
            ae(n.username.plain(),'worker5')
            ae(n['username'].plain(),'worker5')
        for n in issue.messages:
            ae(n.author.username.plain(),'worker5')
            ae(n.author['username'].plain(),'worker5')
            ae(n['author'].username.plain(),'worker5')
            ae(n['author']['username'].plain(),'worker5')


    def testHTMLItemDerefFail(self):
        issue = HTMLItem(self.client, 'issue', '2')
        ae = self.assertEqual
        ae(issue.assignedto.plain(),'')
        ae(issue ['assignedto'].plain(),'')
        ae(issue.priority.plain(),'')
        ae(issue ['priority'].plain(),'')
        m = '[Attempt to look up %s on a missing value]'
        ae(str(issue.priority.name),m%'name')
        ae(str(issue ['priority'].name),m%'name')
        ae(str(issue.assignedto.username),m%'username')
        ae(str(issue ['assignedto'].username),m%'username')
        ae(bool(issue ['assignedto']['username']),False)
        ae(bool(issue ['priority']['name']),False)

def makeForm(args):
    form = cgi.FieldStorage()
    for k,v in args.items():
        if type(v) is type([]):
            [form.list.append(cgi.MiniFieldStorage(k, x)) for x in v]
        elif isinstance(v, FileUpload):
            x = cgi.MiniFieldStorage(k, v.content)
            x.filename = v.filename
            form.list.append(x)
        else:
            form.list.append(cgi.MiniFieldStorage(k, v))
    return form

class FileUpload:
    def __init__(self, content, filename):
        self.content = content
        self.filename = filename

class FormTestParent(object):

    backend = "anydbm"
    def setupDetectors(self):
        pass

    def setUp(self):
        self.dirname = '_test_cgi_form'
        # set up and open a tracker
        self.instance = setupTracker(self.dirname, backend = self.backend)

        # We may want to register separate detectors
        self.setupDetectors()

        # open the database
        self.db = self.instance.open('admin')
        self.db.Otk = MockNull()
        self.db.Otk.data = {}
        self.db.Otk.getall = self.data_get
        self.db.Otk.set = self.data_set
        self.db.tx_Source = "web"
        self.db.user.create(username='Chef', address='chef@bork.bork.bork',
            realname='Bork, Chef', roles='User')
        self.db.user.create(username='mary', address='mary@test.test',
            roles='User', realname='Contrary, Mary')

        self.db.issue.addprop(tx_Source=hyperdb.String())
        self.db.msg.addprop(tx_Source=hyperdb.String())
        self.db.post_init()

    def setupClient(self, form, classname, nodeid=None, template='item', env_addon=None):
        cl = client.Client(self.instance, None, {'PATH_INFO':'/',
            'REQUEST_METHOD':'POST'}, makeForm(form))
        cl.classname = classname
        cl.base = 'http://whoami.com/path/'
        cl.nodeid = nodeid
        cl.language = ('en',)
        cl.userid = '1'
        cl.db = self.db
        cl.user = 'admin'
        cl.template = template
        if env_addon is not None:
            cl.env.update(env_addon)
        return cl

    def data_get(self, key):
        return self.db.Otk.data[key]

    def data_set(self, key, **value):
        self.db.Otk.data[key] = value

    def parseForm(self, form, classname='test', nodeid=None):
        cl = self.setupClient(form, classname, nodeid)
        return cl.parsePropsFromForm(create=1)

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

class SpecialAction(actions.EditItemAction):
    x = False
    def handle(self):
        self.__class__.x = True
        cl = self.db.getclass(self.classname)
        cl.set(self.nodeid, status='2')
        cl.set(self.nodeid, title="Just a test")
        assert 0, "not reached"
        self.db.commit()

def reject_title(db, cl, nodeid, newvalues):
    if 'title' in newvalues:
        raise Reject ("REJECT TITLE CHANGE")

def init_reject(db):
    db.issue.audit("set", reject_title)

def get_extensions(self, what):
    """ For monkey-patch of instance.get_extensions: The old method is
        kept as _get_extensions, we use the new method to return our own
        auditors/reactors.
    """
    if what == 'detectors':
        return [init_reject]
    return self._get_extensions(what)

class SpecialActionTest(FormTestParent):

    def setupDetectors(self):
        self.instance._get_extensions = self.instance.get_extensions
        def ge(what):
            return get_extensions(self.instance, what)
        self.instance.get_extensions = ge

    def setUp(self):
        FormTestParent.setUp(self)

        self.instance.registerAction('special', SpecialAction)
        self.issue = self.db.issue.create (title = "hello", status='1')
        self.db.commit ()
        if 'SENDMAILDEBUG' not in os.environ:
            os.environ['SENDMAILDEBUG'] = 'mail-test2.log'
        self.SENDMAILDEBUG = os.environ['SENDMAILDEBUG']
        page_template = """
        <html>
         <body>
          <p tal:condition="options/error_message|nothing"
             tal:repeat="m options/error_message"
             tal:content="structure m"/>
          <p tal:content="context/title/plain"/>
          <p tal:content="context/status/plain"/>
          <p tal:content="structure context/submit"/>
         </body>
        </html>
        """.strip ()
        self.form = {':action': 'special'}
        cl = self.setupClient(self.form, 'issue', self.issue)
        pt = RoundupPageTemplate()
        pt.pt_edit(page_template, 'text/html')
        self.out = []
        def wh(s):
            self.out.append(s)
        cl.write_html = wh
        def load_template(x):
            return pt
        cl.instance.templates.load = load_template
        cl.selectTemplate = MockNull()
        cl.determine_context = MockNull ()
        def hasPermission(s, p, classname=None, d=None, e=None, **kw):
            return True
        self.hasPermission = actions.Action.hasPermission
        actions.Action.hasPermission = hasPermission
        self.e1 = _HTMLItem.is_edit_ok
        _HTMLItem.is_edit_ok = lambda x : True
        self.e2 = HTMLProperty.is_edit_ok
        HTMLProperty.is_edit_ok = lambda x : True
        # Make sure header check passes
        cl.env['HTTP_REFERER'] = 'http://whoami.com/path/'
        self.client = cl

    def tearDown(self):
        FormTestParent.tearDown(self)
        # Remove monkey-patches
        self.instance.get_extensions = self.instance._get_extensions
        del self.instance._get_extensions
        actions.Action.hasPermission = self.hasPermission
        _HTMLItem.is_edit_ok = self.e1
        HTMLProperty.is_edit_ok = self.e2
        if os.path.exists(self.SENDMAILDEBUG):
            #os.remove(self.SENDMAILDEBUG)
            pass

    def testInnerMain(self):
        cl = self.client
        cl.session_api = MockNull(_sid="1234567890")
        self.form ['@nonce'] = anti_csrf_nonce(cl)
        cl.form = makeForm(self.form)
        # inner_main will re-open the database!
        # Note that in the template above, the rendering of the
        # context/submit button will also call anti_csrf_nonce which
        # does a commit of the otk to the database.
        cl.inner_main()
        cl.db.close()
        print(self.out)
        # Make sure the action was called
        self.assertEqual(SpecialAction.x, True)
        # Check that the Reject worked:
        self.assertNotEqual(-1, self.out[0].index('REJECT TITLE CHANGE'))
        # Re-open db
        self.db.close()
        self.db = self.instance.open ('admin')
        # We shouldn't see any changes
        self.assertEqual(self.db.issue.get(self.issue, 'title'), 'hello')
        self.assertEqual(self.db.issue.get(self.issue, 'status'), '1')

# vim: set et sts=4 sw=4 :
