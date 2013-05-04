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

import unittest, os, shutil, errno, imp, sys, time, pprint, base64, os.path
import logging
import gpgmelib
from email.parser import FeedParser

from roundup.hyperdb import String, Password, Link, Multilink, Date, \
    Interval, DatabaseError, Boolean, Number, Node
from roundup.mailer import Mailer
from roundup import date, password, init, instance, configuration, \
    roundupdb, i18n

from mocknull import MockNull

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

def setupTracker(dirname, backend="anydbm"):
    """Install and initialize new tracker in dirname; return tracker instance.

    If the directory exists, it is wiped out before the operation.

    """
    global config
    try:
        shutil.rmtree(dirname)
    except OSError, error:
        if error.errno not in (errno.ENOENT, errno.ESRCH): raise
    # create the instance
    init.install(dirname, os.path.join(os.path.dirname(__file__),
                                       '..',
                                       'share',
                                       'roundup',
                                       'templates',
                                       'classic'))
    init.write_select_db(dirname, backend)
    config.save(os.path.join(dirname, 'config.ini'))
    tracker = instance.open(dirname)
    if tracker.exists():
        tracker.nuke()
        init.write_select_db(dirname, backend)
    tracker.init(password.Password('sekrit'))
    return tracker

def setupSchema(db, create, module):
    status = module.Class(db, "status", name=String())
    status.setkey("name")
    priority = module.Class(db, "priority", name=String(), order=String())
    priority.setkey("name")
    user = module.Class(db, "user", username=String(), password=Password(),
        assignable=Boolean(), age=Number(), roles=String(), address=String(),
        supervisor=Link('user'),realname=String())
    user.setkey("username")
    file = module.FileClass(db, "file", name=String(), type=String(),
        comment=String(indexme="yes"), fooz=Password())
    file_nidx = module.FileClass(db, "file_nidx", content=String(indexme='no'))
    issue = module.IssueClass(db, "issue", title=String(indexme="yes"),
        status=Link("status"), nosy=Multilink("user"), deadline=Date(),
        foo=Interval(), files=Multilink("file"), assignedto=Link('user'),
        priority=Link('priority'), spam=Multilink('msg'),
        feedback=Link('msg'))
    stuff = module.Class(db, "stuff", stuff=String())
    session = module.Class(db, 'session', title=String())
    msg = module.FileClass(db, "msg", date=Date(),
                           author=Link("user", do_journal='no'),
                           files=Multilink('file'), inreplyto=String(),
                           messageid=String(),
                           recipients=Multilink("user", do_journal='no')
                           )
    session.disableJournalling()
    db.post_init()
    if create:
        user.create(username="admin", roles='Admin',
            password=password.Password('sekrit'))
        user.create(username="fred", roles='User',
            password=password.Password('sekrit'), address='fred@example.com')
        status.create(name="unread")
        status.create(name="in-progress")
        status.create(name="testing")
        status.create(name="resolved")
        priority.create(name="feature", order="2")
        priority.create(name="wish", order="3")
        priority.create(name="bug", order="1")
    db.commit()

    # nosy tests require this
    db.security.addPermissionToRole('User', 'View', 'msg')

class MyTestCase(unittest.TestCase):
    def tearDown(self):
        if hasattr(self, 'db'):
            self.db.close()
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)

    def open_database(self):
        self.db = self.module.Database(config, 'admin')


if os.environ.has_key('LOGGING_LEVEL'):
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
        def filt_iter(*args):
            """ for checking equivalence of filter and filter_iter """
            return list(cls.filter_iter(*args))
        return self.assertEqual, cls.filter, filt_iter

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

    def testRefresh(self):
        self.db.refresh_database()

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
        ustr = u'\xe4\xf6\xfc\u20ac'.encode('utf8')
        nid = self.db.issue.create(title=ustr, status='1')
        self.assertEqual(self.db.issue.get(nid, 'title'), ustr)

        # change and make sure we retrieve the correct value
        ustr2 = u'change \u20ac change'.encode('utf8')
        self.db.issue.set(nid, title=ustr2)
        self.db.commit()
        self.assertEqual(self.db.issue.get(nid, 'title'), ustr2)

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
#    def testMultilinkOrdering(self):
#        for i in range(10):
#            self.db.user.create(username='foo%s'%i)
#        i = self.db.issue.create(title="spam", nosy=['5','3','12','4'])
#        self.db.commit()
#        l = self.db.issue.get(i, "nosy")
#        # all backends should return the Multilink numeric-id-sorted
#        self.assertEqual(l, ['3', '4', '5', '12'])

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
            for d in [date.Date (x) for x in '2038', '1970', '0033', '9999']:
                self.db.issue.set(nid, deadline=d)
                if commit: self.db.commit()
                c = self.db.issue.get(nid, "deadline")
                self.assertEqual(c, d)

    def testDateLeapYear(self):
        nid = self.db.issue.create(title='spam', status='1',
            deadline=date.Date('2008-02-29'))
        self.assertEquals(str(self.db.issue.get(nid, 'deadline')),
            '2008-02-29.00:00:00')
        self.assertEquals(self.db.issue.filter(None,
            {'deadline': '2008-02-29'}), [nid])
        self.assertEquals(list(self.db.issue.filter_iter(None,
            {'deadline': '2008-02-29'})), [nid])
        self.db.issue.set(nid, deadline=date.Date('2008-03-01'))
        self.assertEquals(str(self.db.issue.get(nid, 'deadline')),
            '2008-03-01.00:00:00')
        self.assertEquals(self.db.issue.filter(None,
            {'deadline': '2008-02-29'}), [])
        self.assertEquals(list(self.db.issue.filter_iter(None,
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

        self.assert_(self.db.status.is_retired('1'))

        # make sure the list is different
        self.assertNotEqual(a, self.db.status.list())

        # can still access the node if necessary
        self.assertEqual(self.db.status.get('1', 'name'), b)
        self.assertRaises(IndexError, self.db.status.set, '1', name='hello')
        self.db.commit()
        self.assert_(self.db.status.is_retired('1'))
        self.assertEqual(self.db.status.get('1', 'name'), b)
        self.assertNotEqual(a, self.db.status.list())

        # try to restore retired node
        self.db.status.restore('1')

        self.assert_(not self.db.status.is_retired('1'))

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
        keys = params.keys()
        keys.sort()
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
        self.assertEquals(self.db.indexer.search([], self.db.issue), {})
        self.assertEquals(self.db.indexer.search(['hello'], self.db.issue),
            {i1: {'files': [f1]}})
        # content='world' has the wrong content-type and shouldn't be indexed
        self.assertEquals(self.db.indexer.search(['world'], self.db.issue), {})
        self.assertEquals(self.db.indexer.search(['frooz'], self.db.issue),
            {i2: {}})
        self.assertEquals(self.db.indexer.search(['flebble'], self.db.issue),
            {i1: {}, i2: {}})

        # test AND'ing of search terms
        self.assertEquals(self.db.indexer.search(['frooz', 'flebble'],
            self.db.issue), {i2: {}})

        # unindexed stopword
        self.assertEquals(self.db.indexer.search(['the'], self.db.issue), {})

    def testIndexerSearchingLink(self):
        m1 = self.db.msg.create(content="one two")
        i1 = self.db.issue.create(messages=[m1])
        m2 = self.db.msg.create(content="two three")
        i2 = self.db.issue.create(feedback=m2)
        self.db.commit()
        self.assertEquals(self.db.indexer.search(['two'], self.db.issue),
            {i1: {'messages': [m1]}, i2: {'feedback': [m2]}})

    def testIndexerSearchMulti(self):
        m1 = self.db.msg.create(content="one two")
        m2 = self.db.msg.create(content="two three")
        i1 = self.db.issue.create(messages=[m1])
        i2 = self.db.issue.create(spam=[m2])
        self.db.commit()
        self.assertEquals(self.db.indexer.search([], self.db.issue), {})
        self.assertEquals(self.db.indexer.search(['one'], self.db.issue),
            {i1: {'messages': [m1]}})
        self.assertEquals(self.db.indexer.search(['two'], self.db.issue),
            {i1: {'messages': [m1]}, i2: {'spam': [m2]}})
        self.assertEquals(self.db.indexer.search(['three'], self.db.issue),
            {i2: {'spam': [m2]}})

    def testReindexingChange(self):
        search = self.db.indexer.search
        issue = self.db.issue
        i1 = issue.create(title="flebble plop")
        i2 = issue.create(title="flebble frooz")
        self.db.commit()
        self.assertEquals(search(['plop'], issue), {i1: {}})
        self.assertEquals(search(['flebble'], issue), {i1: {}, i2: {}})

        # change i1's title
        issue.set(i1, title="plop")
        self.db.commit()
        self.assertEquals(search(['plop'], issue), {i1: {}})
        self.assertEquals(search(['flebble'], issue), {i2: {}})

    def testReindexingClear(self):
        search = self.db.indexer.search
        issue = self.db.issue
        i1 = issue.create(title="flebble plop")
        i2 = issue.create(title="flebble frooz")
        self.db.commit()
        self.assertEquals(search(['plop'], issue), {i1: {}})
        self.assertEquals(search(['flebble'], issue), {i1: {}, i2: {}})

        # unset i1's title
        issue.set(i1, title="")
        self.db.commit()
        self.assertEquals(search(['plop'], issue), {})
        self.assertEquals(search(['flebble'], issue), {i2: {}})

    def testFileClassReindexing(self):
        f1 = self.db.file.create(content='hello')
        f2 = self.db.file.create(content='hello, world')
        i1 = self.db.issue.create(files=[f1, f2])
        self.db.commit()
        d = self.db.indexer.search(['hello'], self.db.issue)
        self.assert_(d.has_key(i1))
        d[i1]['files'].sort()
        self.assertEquals(d, {i1: {'files': [f1, f2]}})
        self.assertEquals(self.db.indexer.search(['world'], self.db.issue),
            {i1: {'files': [f2]}})
        self.db.file.set(f1, content="world")
        self.db.commit()
        d = self.db.indexer.search(['world'], self.db.issue)
        d[i1]['files'].sort()
        self.assertEquals(d, {i1: {'files': [f1, f2]}})
        self.assertEquals(self.db.indexer.search(['hello'], self.db.issue),
            {i1: {'files': [f2]}})

    def testFileClassIndexingNoNoNo(self):
        f1 = self.db.file.create(content='hello')
        self.db.commit()
        self.assertEquals(self.db.indexer.search(['hello'], self.db.file),
            {'1': {}})

        f1 = self.db.file_nidx.create(content='hello')
        self.db.commit()
        self.assertEquals(self.db.indexer.search(['hello'], self.db.file_nidx),
            {})

    def testForcedReindexing(self):
        self.db.issue.create(title="flebble frooz")
        self.db.commit()
        self.assertEquals(self.db.indexer.search(['flebble'], self.db.issue),
            {'1': {}})
        self.db.indexer.quiet = 1
        self.db.indexer.force_reindex()
        self.db.post_init()
        self.db.indexer.quiet = 9
        self.assertEquals(self.db.indexer.search(['flebble'], self.db.issue),
            {'1': {}})

    def testIndexingPropertiesOnImport(self):
        # import an issue
        title = 'Bzzt'
        nodeid = self.db.issue.import_list(['title', 'messages', 'files',
            'spam', 'nosy', 'superseder'], [repr(title), '[]', '[]',
            '[]', '[]', '[]'])
        self.db.commit()

        # Content of title attribute is indexed
        self.assertEquals(self.db.indexer.search([title], self.db.issue),
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
        ae, filter, filter_iter = self.filteringSetup()
        for filt in filter, filter_iter:
            ae(filt(None, {'id': '1'}, ('+','id'), (None,None)), ['1'])
            ae(filt(None, {'id': '2'}, ('+','id'), (None,None)), ['2'])
            ae(filt(None, {'id': '100'}, ('+','id'), (None,None)), [])

    def testFilteringBoolean(self):
        ae, filter, filter_iter = self.filteringSetup('user')
        a = 'assignable'
        for filt in filter, filter_iter:
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
        ae, filter, filter_iter = self.filteringSetup('user')
        for filt in filter, filter_iter:
            ae(filt(None, {'age': '1'}, ('+','id'), (None,None)), ['3'])
            ae(filt(None, {'age': '1.5'}, ('+','id'), (None,None)), ['4'])
            ae(filt(None, {'age': '2'}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {'age': ['1','2']}, ('+','id'), (None,None)),
                ['3','5'])
            ae(filt(None, {'age': 2}, ('+','id'), (None,None)), ['5'])
            ae(filt(None, {'age': [1,2]}, ('+','id'), (None,None)), ['3','5'])

    def testFilteringString(self):
        ae, filter, filter_iter = self.filteringSetup()
        for filt in filter, filter_iter:
            ae(filt(None, {'title': ['one']}, ('+','id'), (None,None)), ['1'])
            ae(filt(None, {'title': ['issue one']}, ('+','id'), (None,None)),
                ['1'])
            ae(filt(None, {'title': ['issue', 'one']}, ('+','id'), (None,None)),
                ['1'])
            ae(filt(None, {'title': ['issue']}, ('+','id'), (None,None)),
                ['1','2','3'])
            ae(filt(None, {'title': ['one', 'two']}, ('+','id'), (None,None)),
                [])

    def testFilteringLink(self):
        ae, filter, filter_iter = self.filteringSetup()
        a = 'assignedto'
        grp = (None, None)
        for filt in filter, filter_iter:
            ae(filt(None, {'status': '1'}, ('+','id'), grp), ['2','3'])
            ae(filt(None, {a: '-1'}, ('+','id'), grp), ['3','4'])
            ae(filt(None, {a: None}, ('+','id'), grp), ['3','4'])
            ae(filt(None, {a: [None]}, ('+','id'), grp), ['3','4'])
            ae(filt(None, {a: ['-1', None]}, ('+','id'), grp), ['3','4'])
            ae(filt(None, {a: ['1', None]}, ('+','id'), grp), ['1', '3','4'])

    def testFilteringMultilinkAndGroup(self):
        """testFilteringMultilinkAndGroup:
        See roundup Bug 1541128: apparently grouping by something and
        searching a Multilink failed with MySQL 5.0
        """
        ae, filter, filter_iter = self.filteringSetup()
        for f in filter, filter_iter:
            ae(f(None, {'files': '1'}, ('-','activity'), ('+','status')), ['4'])

    def testFilteringRetired(self):
        ae, filter, filter_iter = self.filteringSetup()
        self.db.issue.retire('2')
        for f in filter, filter_iter:
            ae(f(None, {'status': '1'}, ('+','id'), (None,None)), ['3'])

    def testFilteringMultilink(self):
        ae, filter, filter_iter = self.filteringSetup()
        for filt in filter, filter_iter:
            ae(filt(None, {'nosy': '3'}, ('+','id'), (None,None)), ['4'])
            ae(filt(None, {'nosy': '-1'}, ('+','id'), (None,None)), ['1', '2'])
            ae(filt(None, {'nosy': ['1','2']}, ('+', 'status'),
                ('-', 'deadline')), ['4', '3'])

    def testFilteringMany(self):
        ae, filter, filter_iter = self.filteringSetup()
        for f in filter, filter_iter:
            ae(f(None, {'nosy': '2', 'status': '1'}, ('+','id'), (None,None)),
                ['3'])

    def testFilteringRangeBasic(self):
        ae, filter, filter_iter = self.filteringSetup()
        d = 'deadline'
        for f in filter, filter_iter:
            ae(f(None, {d: 'from 2003-02-10 to 2003-02-23'}), ['1','3'])
            ae(f(None, {d: '2003-02-10; 2003-02-23'}), ['1','3'])
            ae(f(None, {d: '; 2003-02-16'}), ['2'])

    def testFilteringRangeTwoSyntaxes(self):
        ae, filter, filter_iter = self.filteringSetup()
        for filt in filter, filter_iter:
            ae(filt(None, {'deadline': 'from 2003-02-16'}), ['1', '3', '4'])
            ae(filt(None, {'deadline': '2003-02-16;'}), ['1', '3', '4'])

    def testFilteringRangeYearMonthDay(self):
        ae, filter, filter_iter = self.filteringSetup()
        for filt in filter, filter_iter:
            ae(filt(None, {'deadline': '2002'}), [])
            ae(filt(None, {'deadline': '2003'}), ['1', '2', '3'])
            ae(filt(None, {'deadline': '2004'}), ['4'])
            ae(filt(None, {'deadline': '2003-02-16'}), ['1'])
            ae(filt(None, {'deadline': '2003-02-17'}), [])

    def testFilteringRangeMonths(self):
        ae, filter, filter_iter = self.filteringSetup()
        for month in range(1, 13):
            for n in range(1, month+1):
                i = self.db.issue.create(title='%d.%d'%(month, n),
                    deadline=date.Date('2001-%02d-%02d.00:00'%(month, n)))
        self.db.commit()

        for month in range(1, 13):
            for filt in filter, filter_iter:
                r = filt(None, dict(deadline='2001-%02d'%month))
                assert len(r) == month, 'month %d != length %d'%(month, len(r))

    def testFilteringRangeInterval(self):
        ae, filter, filter_iter = self.filteringSetup()
        for filt in filter, filter_iter:
            ae(filt(None, {'foo': 'from 0:50 to 2:00'}), ['1'])
            ae(filt(None, {'foo': 'from 0:50 to 1d 2:00'}), ['1', '2'])
            ae(filt(None, {'foo': 'from 5:50'}), ['2'])
            ae(filt(None, {'foo': 'to 0:05'}), [])

    def testFilteringRangeGeekInterval(self):
        ae, filter, filter_iter = self.filteringSetup()
        for issue in (
                { 'deadline': date.Date('. -2d')},
                { 'deadline': date.Date('. -1d')},
                { 'deadline': date.Date('. -8d')},
                ):
            self.db.issue.create(**issue)
        for filt in filter, filter_iter:
            ae(filt(None, {'deadline': '-2d;'}), ['5', '6'])
            ae(filt(None, {'deadline': '-1d;'}), ['6'])
            ae(filt(None, {'deadline': '-1w;'}), ['5', '6'])

    def testFilteringIntervalSort(self):
        # 1: '1:10'
        # 2: '1d'
        # 3: None
        # 4: '0:10'
        ae, filter, filter_iter = self.filteringSetup()
        for filt in filter, filter_iter:
            # ascending should sort None, 1:10, 1d
            ae(filt(None, {}, ('+','foo'), (None,None)), ['3', '4', '1', '2'])
            # descending should sort 1d, 1:10, None
            ae(filt(None, {}, ('-','foo'), (None,None)), ['2', '1', '4', '3'])

    def testFilteringStringSort(self):
        # 1: 'issue one'
        # 2: 'issue two'
        # 3: 'issue three'
        # 4: 'non four'
        ae, filter, filter_iter = self.filteringSetup()
        for filt in filter, filter_iter:
            ae(filt(None, {}, ('+','title')), ['1', '3', '2', '4'])
            ae(filt(None, {}, ('-','title')), ['4', '2', '3', '1'])
        # Test string case: For now allow both, w/wo case matching.
        # 1: 'issue one'
        # 2: 'issue two'
        # 3: 'Issue three'
        # 4: 'non four'
        self.db.issue.set('3', title='Issue three')
        for filt in filter, filter_iter:
            ae(filt(None, {}, ('+','title')), ['1', '3', '2', '4'])
            ae(filt(None, {}, ('-','title')), ['4', '2', '3', '1'])
        # Obscure bug in anydbm backend trying to convert to number
        # 1: '1st issue'
        # 2: '2'
        # 3: 'Issue three'
        # 4: 'non four'
        self.db.issue.set('1', title='1st issue')
        self.db.issue.set('2', title='2')
        for filt in filter, filter_iter:
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
        ae, filt, dummy = self.filteringSetup()
        ae(filt(None, {}, ('+','nosy'), (None,None)), ['1', '2', '4', '3'])
        ae(filt(None, {}, ('-','nosy'), (None,None)), ['4', '3', '1', '2'])

    def testFilteringMultilinkSortGroup(self):
        # 1: status: 2 "in-progress" nosy: []
        # 2: status: 1 "unread"      nosy: []
        # 3: status: 1 "unread"      nosy: ['admin','fred']
        # 4: status: 3 "testing"     nosy: ['admin','bleep','fred']
        # Note that we don't test filter_iter here, Multilink sort-order
        # isn't defined for that.
        ae, filt, dummy = self.filteringSetup()
        ae(filt(None, {}, ('+','nosy'), ('+','status')), ['1', '4', '2', '3'])
        ae(filt(None, {}, ('-','nosy'), ('+','status')), ['1', '4', '3', '2'])
        ae(filt(None, {}, ('+','nosy'), ('-','status')), ['2', '3', '4', '1'])
        ae(filt(None, {}, ('-','nosy'), ('-','status')), ['3', '2', '4', '1'])
        ae(filt(None, {}, ('+','status'), ('+','nosy')), ['1', '2', '4', '3'])
        ae(filt(None, {}, ('-','status'), ('+','nosy')), ['2', '1', '4', '3'])
        ae(filt(None, {}, ('+','status'), ('-','nosy')), ['4', '3', '1', '2'])
        ae(filt(None, {}, ('-','status'), ('-','nosy')), ['4', '3', '2', '1'])

    def testFilteringLinkSortGroup(self):
        # 1: status: 2 -> 'i', priority: 3 -> 1
        # 2: status: 1 -> 'u', priority: 3 -> 1
        # 3: status: 1 -> 'u', priority: 2 -> 3
        # 4: status: 3 -> 't', priority: 2 -> 3
        ae, filter, filter_iter = self.filteringSetup()
        for filt in filter, filter_iter:
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
        ae, filter, filter_iter = self.filteringSetup()
        for f in filter, filter_iter:
            # ascending
            ae(f(None, {}, ('+','deadline'), (None,None)), ['2', '1', '3', '4'])
            # descending
            ae(f(None, {}, ('-','deadline'), (None,None)), ['4', '3', '1', '2'])

    def testFilteringDateSortPriorityGroup(self):
        # '1': '2003-02-16.22:50'  1 => 2
        # '2': '2003-01-01.00:00'  3 => 1
        # '3': '2003-02-18'        2 => 3
        # '4': '2004-03-08'        1 => 2
        ae, filter, filter_iter = self.filteringSetup()

        for filt in filter, filter_iter:
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
        ae, filter, filter_iter = self.filteringSetupTransitiveSearch('user')
        for f in filter, filter_iter:
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

    def testFilteringTransitiveLinkSort(self):
        ae, filter, filter_iter = self.filteringSetupTransitiveSearch()
        ae, ufilter, ufilter_iter = self.iterSetup('user')
        # Need to make ceo his own (and first two users') supervisor,
        # otherwise we will depend on sorting order of NULL values.
        # Leave that to a separate test.
        self.db.user.set('1', supervisor = '3')
        self.db.user.set('2', supervisor = '3')
        self.db.user.set('3', supervisor = '3')
        for ufilt in ufilter, ufilter_iter:
            ae(ufilt(None, {'supervisor':'3'}, []), ['1', '2', '3', '4', '5'])
            ae(ufilt(None, {}, [('+','supervisor.supervisor.supervisor'),
                ('+','supervisor.supervisor'), ('+','supervisor'),
                ('+','username')]),
                ['1', '3', '2', '4', '5', '6', '7', '8', '9', '10'])
            ae(ufilt(None, {}, [('+','supervisor.supervisor.supervisor'),
                ('-','supervisor.supervisor'), ('-','supervisor'),
                ('+','username')]),
                ['8', '9', '10', '6', '7', '1', '3', '2', '4', '5'])
        for f in filter, filter_iter:
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
        ae, filter, filter_iter = self.filteringSetupTransitiveSearch()
        ae, ufilter, ufilter_iter = self.iterSetup('user')
        for ufilt in ufilter, ufilter_iter:
            ae(ufilt(None, {}, [('+','supervisor.supervisor.supervisor'),
                ('+','supervisor.supervisor'), ('+','supervisor'),
                ('+','username')]),
                ['1', '3', '2', '4', '5', '6', '7', '8', '9', '10'])
            ae(ufilt(None, {}, [('+','supervisor.supervisor.supervisor'),
                ('-','supervisor.supervisor'), ('-','supervisor'),
                ('+','username')]),
                ['8', '9', '10', '6', '7', '4', '5', '1', '3', '2'])
        for f in filter, filter_iter:
            ae(f(None, {}, [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('+','assignedto.supervisor'), ('+','assignedto')]),
                ['1', '2', '3', '4', '5', '6', '7', '8'])
            ae(f(None, {}, [('+','assignedto.supervisor.supervisor.supervisor'),
                ('+','assignedto.supervisor.supervisor'),
                ('-','assignedto.supervisor'), ('+','assignedto')]),
                ['4', '5', '6', '7', '8', '1', '2', '3'])

    def testFilteringTransitiveLinkIssue(self):
        ae, filter, filter_iter = self.filteringSetupTransitiveSearch()
        for filt in filter, filter_iter:
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
        ae, filter, filter_iter = self.filteringSetupTransitiveSearch()
        for filt in filter, filter_iter:
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
        ae, filt, dummy = self.filteringSetupTransitiveSearch()
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
        ae(filt(None, {}, [('+','messages'), ('+','messages.author')]),
            ['6', '7', '8', '5', '4', '3', '1', '2'])
        ae(filt(None, {}, [('+','messages.author'), ('+','messages')]),
            ['6', '7', '8', '5', '4', '3', '1', '2'])
        self.db.msg.setorderprop('author')
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
        ae(filt(None, {}, [('+','messages.author'), ('-','messages')]),
            ['3', '1', '2', '6', '7', '5', '4', '8'])

    def testFilteringSortId(self):
        ae, filter, filter_iter = self.filteringSetupTransitiveSearch('user')
        for filt in filter, filter_iter:
            ae(filt(None, {}, ('+','id')),
                ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])

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
        ae, dummy1, dummy2 = self.filteringSetup()
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
            for cn,klass in self.db.classes.items():
                names = klass.export_propnames()
                cl = export[cn] = [names+['is retired']]
                for id in klass.getnodeids():
                    cl.append(klass.export_list(names, id))
                    if hasattr(klass, 'export_files'):
                        klass.export_files('_test_export', id)
                journals[cn] = klass.export_journals()

            self.nukeAndCreate()

            # import
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
            # This is needed, otherwise journals won't be there for anydbm
            self.db.commit()
        finally:
            shutil.rmtree('_test_export')

        # compare with snapshot of the database
        for cn, items in orig.iteritems():
            klass = self.db.classes[cn]
            propdefs = klass.getprops(1)
            # ensure retired items are retired :)
            l = items.keys(); l.sort()
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
        for jc, items in origj.iteritems():
            for id, oj in items.iteritems():
                rj = self.db.getjournal(jc, id)
                # Both mysql and postgresql have some minor issues with
                # rounded seconds on export/import, so we compare only
                # the integer part.
                for j in oj:
                    j[1].second = float(int(j[1].second))
                for j in rj:
                    j[1].second = float(int(j[1].second))
                oj.sort()
                rj.sort()
                ae(oj, rj)

        # make sure the retired items are actually imported
        ae(self.db.user.get('4', 'username'), 'blop')
        ae(self.db.issue.get('2', 'title'), 'issue two')

        # make sure id counters are set correctly
        maxid = max([int(id) for id in self.db.user.list()])
        newid = self.db.user.create(username='testing')
        assert newid > maxid

    # test import/export via admin interface
    def testAdminImportExport(self):
        import roundup.admin
        import csv
        # use the filtering setup to create a bunch of items
        ae, dummy1, dummy2 = self.filteringSetup()
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
            self.failUnless(output [0].startswith
                ('Warning: config csv_field_size should be at least'))
            self.failUnless(int(output[0].split()[-1]) > 500)

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

    def testAddProperty(self):
        self.db.issue.create(title="spam", status='1')
        self.db.commit()

        self.db.issue.addprop(fixer=Link("user"))
        # force any post-init stuff to happen
        self.db.post_init()
        props = self.db.issue.getprops()
        keys = props.keys()
        keys.sort()
        self.assertEqual(keys, ['activity', 'actor', 'assignedto', 'creation',
            'creator', 'deadline', 'feedback', 'files', 'fixer', 'foo', 'id', 'messages',
            'nosy', 'priority', 'spam', 'status', 'superseder', 'title'])
        self.assertEqual(self.db.issue.get('1', "fixer"), None)

    def testRemoveProperty(self):
        self.db.issue.create(title="spam", status='1')
        self.db.commit()

        del self.db.issue.properties['title']
        self.db.post_init()
        props = self.db.issue.getprops()
        keys = props.keys()
        keys.sort()
        self.assertEqual(keys, ['activity', 'actor', 'assignedto', 'creation',
            'creator', 'deadline', 'feedback', 'files', 'foo', 'id', 'messages',
            'nosy', 'priority', 'spam', 'status', 'superseder'])
        self.assertEqual(self.db.issue.list(), ['1'])

    def testAddRemoveProperty(self):
        self.db.issue.create(title="spam", status='1')
        self.db.commit()

        self.db.issue.addprop(fixer=Link("user"))
        del self.db.issue.properties['title']
        self.db.post_init()
        props = self.db.issue.getprops()
        keys = props.keys()
        keys.sort()
        self.assertEqual(keys, ['activity', 'actor', 'assignedto', 'creation',
            'creator', 'deadline', 'feedback', 'files', 'fixer', 'foo', 'id',
            'messages', 'nosy', 'priority', 'spam', 'status', 'superseder'])
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
            f1 = db.file.create(name="test1.txt", content="x" * 20)
            f2 = db.file.create(name="test2.txt", content="y" * 5000)
            m  = db.msg.create(content="one two", author="admin",
                files = [f1, f2])
            i  = db.issue.create(title='spam', files = [f1, f2],
                messages = [m], nosy = [db.user.lookup("fred")])

            db.issue.nosymessage(i, m, {})
            mail_msg = str(res["mail_msg"])
            self.assertEqual(res["mail_to"], ["fred@example.com"])
            self.assert_("From: admin" in mail_msg)
            self.assert_("Subject: [issue1] spam" in mail_msg)
            self.assert_("New submission from admin" in mail_msg)
            self.assert_("one two" in mail_msg)
            self.assert_("File 'test1.txt' not attached" not in mail_msg)
            self.assert_(base64.encodestring("xxx").rstrip() in mail_msg)
            self.assert_("File 'test2.txt' not attached" in mail_msg)
            self.assert_(base64.encodestring("yyy").rstrip() not in mail_msg)
        finally :
            roundupdb._ = old_translate_
            Mailer.smtp_send = backup

    def testPGPNosyMail(self) :
        """Creates one issue with two attachments, one smaller and one larger
           than the set max_attachment_size. Recipients are one with and
           one without encryption enabled via a gpg group.
        """
        if gpgmelib.pyme is None:
            print "Skipping PGPNosy test"
            return
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
            f1 = db.file.create(name="test1.txt", content="x" * 20)
            f2 = db.file.create(name="test2.txt", content="y" * 5000)
            m  = db.msg.create(content="one two", author="admin",
                files = [f1, f2])
            i  = db.issue.create(title='spam', files = [f1, f2],
                messages = [m], nosy = [db.user.lookup("fred"), john])

            db.issue.nosymessage(i, m, {})
            res.sort(key=lambda x: x['mail_to'])
            self.assertEqual(res[0]["mail_to"], ["fred@example.com"])
            self.assertEqual(res[1]["mail_to"], ["john@test.test"])
            mail_msg = str(res[0]["mail_msg"])
            self.assert_("From: admin" in mail_msg)
            self.assert_("Subject: [issue1] spam" in mail_msg)
            self.assert_("New submission from admin" in mail_msg)
            self.assert_("one two" in mail_msg)
            self.assert_("File 'test1.txt' not attached" not in mail_msg)
            self.assert_(base64.encodestring("xxx").rstrip() in mail_msg)
            self.assert_("File 'test2.txt' not attached" in mail_msg)
            self.assert_(base64.encodestring("yyy").rstrip() not in mail_msg)
            fp = FeedParser()
            mail_msg = str(res[1]["mail_msg"])
            fp.feed(mail_msg)
            parts = fp.close().get_payload()
            self.assertEqual(len(parts),2)
            self.assertEqual(parts[0].get_payload().strip(), 'Version: 1')
            crypt = gpgmelib.pyme.core.Data(parts[1].get_payload())
            plain = gpgmelib.pyme.core.Data()
            ctx = gpgmelib.pyme.core.Context()
            res = ctx.op_decrypt(crypt, plain)
            self.assertEqual(res, None)
            plain.seek(0,0)
            fp = FeedParser()
            fp.feed(plain.read())
            self.assert_("From: admin" in mail_msg)
            self.assert_("Subject: [issue1] spam" in mail_msg)
            mail_msg = str(fp.close())
            self.assert_("New submission from admin" in mail_msg)
            self.assert_("one two" in mail_msg)
            self.assert_("File 'test1.txt' not attached" not in mail_msg)
            self.assert_(base64.encodestring("xxx").rstrip() in mail_msg)
            self.assert_("File 'test2.txt' not attached" in mail_msg)
            self.assert_(base64.encodestring("yyy").rstrip() not in mail_msg)
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
        l = a.getprops().keys()
        l.sort()
        self.assert_(l, ['activity', 'actor', 'content', 'created',
            'creation', 'type'])

    def init_ab(self):
        self.open_database()
        a = self.module.Class(self.db, "a", name=String())
        a.setkey("name")
        b = self.module.Class(self.db, "b", name=String(),
            fooz=Multilink('a'))
        b.setkey("name")
        self.db.post_init()

    def test_addNewClass(self):
        self.init_a()

        self.assertRaises(ValueError, self.module.Class, self.db, "a",
            name=String())

        aid = self.db.a.create(name='apple')
        self.db.commit(); self.db.close()

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
        self.assert_(not self.db.a.get(aid, 'newnum'))
        self.assert_(not self.db.a.get(aid, 'newbool'))
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
        ae, filter, filter_iter = self.filteringSetupTransitiveSearch()
        ae, ufilter, ufilter_iter = self.iterSetup('user')
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
            for x in range(4):
                assert(('user', nodeid) in self.db.cache)
                n = self.db.user.getnode(nodeid)
                for k, v in user_result[nodeid].iteritems():
                    ae((k, n[k]), (k, v))
                for k in 'creation', 'activity':
                    assert(n[k])
                nodeid = n.supervisor
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
            for k, v in issue_result[id].iteritems():
                ae((k, n[k]), (k, v))
            for k in 'creation', 'activity':
                assert(n[k])
            nodeid = n.assignedto
            for x in range(4):
                assert(('user', nodeid) in self.db.cache)
                n = self.db.user.getnode(nodeid)
                for k, v in user_result[nodeid].iteritems():
                    ae((k, n[k]), (k, v))
                for k in 'creation', 'activity':
                    assert(n[k])
                nodeid = n.supervisor
            self.db.clearCache()
        ae (result, ['4', '5', '6', '7', '8', '1', '2', '3'])


class ClassicInitTest(unittest.TestCase):
    count = 0
    db = None

    def setUp(self):
        ClassicInitTest.count = ClassicInitTest.count + 1
        self.dirname = '_test_init_%s'%self.count
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

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

    def tearDown(self):
        if self.db is not None:
            self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

class ConcurrentDBTest(ClassicInitTest):
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


# vim: set et sts=4 sw=4 :
