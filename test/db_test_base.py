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
# 
# $Id: db_test_base.py,v 1.27.2.7 2004-06-24 07:14:49 richard Exp $ 

import unittest, os, shutil, errno, imp, sys, time, pprint

from roundup.hyperdb import String, Password, Link, Multilink, Date, \
    Interval, DatabaseError, Boolean, Number, Node
from roundup import date, password
from roundup import init

def setupSchema(db, create, module):
    status = module.Class(db, "status", name=String())
    status.setkey("name")
    priority = module.Class(db, "priority", name=String(), order=String())
    priority.setkey("name")
    user = module.Class(db, "user", username=String(), password=Password(),
        assignable=Boolean(), age=Number(), roles=String())
    user.setkey("username")
    file = module.FileClass(db, "file", name=String(), type=String(),
        comment=String(indexme="yes"), fooz=Password())
    issue = module.IssueClass(db, "issue", title=String(indexme="yes"),
        status=Link("status"), nosy=Multilink("user"), deadline=Date(),
        foo=Interval(), files=Multilink("file"), assignedto=Link('user'),
        priority=Link('priority'))
    stuff = module.Class(db, "stuff", stuff=String())
    session = module.Class(db, 'session', title=String())
    session.disableJournalling()
    db.post_init()
    if create:
        user.create(username="admin", roles='Admin',
            password=password.Password('sekrit'))
        user.create(username="fred", roles='User',
            password=password.Password('sekrit'))
        status.create(name="unread")
        status.create(name="in-progress")
        status.create(name="testing")
        status.create(name="resolved")
        priority.create(name="feature", order="2")
        priority.create(name="wish", order="3")
        priority.create(name="bug", order="1")
    db.commit()

class MyTestCase(unittest.TestCase):
    def tearDown(self):
        if hasattr(self, 'db'):
            self.db.close()
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)

class config:
    DATABASE='_test_dir'
    MAILHOST = 'localhost'
    MAIL_DOMAIN = 'fill.me.in.'
    TRACKER_NAME = 'Roundup issue tracker'
    TRACKER_EMAIL = 'issue_tracker@%s'%MAIL_DOMAIN
    TRACKER_WEB = 'http://some.useful.url/'
    ADMIN_EMAIL = 'roundup-admin@%s'%MAIL_DOMAIN
    FILTER_POSITION = 'bottom'      # one of 'top', 'bottom', 'top and bottom'
    ANONYMOUS_ACCESS = 'deny'       # either 'deny' or 'allow'
    ANONYMOUS_REGISTER = 'deny'     # either 'deny' or 'allow'
    MESSAGES_TO_AUTHOR = 'no'       # either 'yes' or 'no'
    EMAIL_SIGNATURE_POSITION = 'bottom'


class DBTest(MyTestCase):
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = self.module.Database(config, 'admin')
        setupSchema(self.db, 1, self.module)

    def testRefresh(self):
        self.db.refresh_database()

    #
    # automatic properties (well, the two easy ones anyway)
    #
    def testCreatorProperty(self):
        i = self.db.issue
        id1 = i.create(title='spam')
        self.db.commit()
        self.db.close()
        self.db = self.module.Database(config, 'fred')
        setupSchema(self.db, 0, self.module)
        i = self.db.issue
        id2 = i.create(title='spam')
        self.assertNotEqual(id1, id2)
        self.assertNotEqual(i.get(id1, 'creator'), i.get(id2, 'creator'))

    def testActorProperty(self):
        i = self.db.issue
        id1 = i.create(title='spam')
        self.db.commit()
        self.db.close()
        self.db = self.module.Database(config, 'fred')
        setupSchema(self.db, 0, self.module)
        i = self.db.issue
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
            self.assertNotEqual(b, date.Date('1970-1-1 00:00:00'))

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
        self.db.status.retire('1')
        # make sure the list is different 
        self.assertNotEqual(a, self.db.status.list())
        # can still access the node if necessary
        self.assertEqual(self.db.status.get('1', 'name'), b)
        self.assertRaises(IndexError, self.db.status.set, '1', name='hello')
        self.db.commit()
        self.assertEqual(self.db.status.get('1', 'name'), b)
        self.assertNotEqual(a, self.db.status.list())
        # try to restore retired node
        self.db.status.restore('1')
 
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

    def testJournals(self):
        self.db.user.create(username="mary")
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

        # journal entry for unlink
        self.db.issue.set('1', assignedto='2')
        self.db.commit()
        journal = self.db.getjournal('user', '1')
        self.assertEqual(3, len(journal))
        (nodeid, date_stamp, journaltag, action, params) = journal[2]
        self.assertEqual('1', nodeid)
        self.assertEqual('1', journaltag)
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
        i2 = self.db.issue.create(title="flebble frooz")
        self.db.commit()
        self.assertEquals(self.db.indexer.search(['hello'], self.db.issue),
            {i1: {'files': [f1]}})
        self.assertEquals(self.db.indexer.search(['world'], self.db.issue), {})
        self.assertEquals(self.db.indexer.search(['frooz'], self.db.issue),
            {i2: {}})
        self.assertEquals(self.db.indexer.search(['flebble'], self.db.issue),
            {i1: {}, i2: {}})

    def testReindexing(self):
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
        self.assertEqual(self.db.issue.find(status={'1':1, '3':1}),
            [one, three, four])
        self.assertEqual(self.db.issue.find(assignedto={None:1, '1':1}),
            [one, three, four])

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

    def filteringSetup(self):
        for user in (
                {'username': 'bleep', 'age': 1},
                {'username': 'blop', 'age': 1.5},
                {'username': 'blorp', 'age': 2}):
            self.db.user.create(**user)
        iss = self.db.issue
        for issue in (
                {'title': 'issue one', 'status': '2', 'assignedto': '1',
                    'foo': date.Interval('1:10'), 'priority': '1',
                    'deadline': date.Date('2003-01-01.00:00')},
                {'title': 'issue two', 'status': '1', 'assignedto': '2',
                    'foo': date.Interval('1d'), 'priority': '3',
                    'deadline': date.Date('2003-02-16.22:50')},
                    {'title': 'issue three', 'status': '1', 'priority': '2',
                    'nosy': ['1','2'], 'deadline': date.Date('2003-02-18')},
                {'title': 'non four', 'status': '3',
                    'foo': date.Interval('0:10'), 'priority': '1',
                    'nosy': ['1'], 'deadline': date.Date('2004-03-08')}):
            self.db.issue.create(**issue)
        file_content = ''.join([chr(i) for i in range(255)])
        self.db.file.create(content=file_content)
        self.db.commit()
        return self.assertEqual, self.db.issue.filter

    def testFilteringID(self):
        ae, filt = self.filteringSetup()
        ae(filt(None, {'id': '1'}, ('+','id'), (None,None)), ['1'])
        ae(filt(None, {'id': '2'}, ('+','id'), (None,None)), ['2'])
        ae(filt(None, {'id': '10'}, ('+','id'), (None,None)), [])

    def testFilteringNumber(self):
        self.filteringSetup()
        ae, filt = self.assertEqual, self.db.user.filter
        ae(filt(None, {'age': '1'}, ('+','id'), (None,None)), ['3'])
        ae(filt(None, {'age': '1.5'}, ('+','id'), (None,None)), ['4'])
        ae(filt(None, {'age': '2'}, ('+','id'), (None,None)), ['5'])
        ae(filt(None, {'age': ['1','2']}, ('+','id'), (None,None)), ['3','5'])

    def testFilteringString(self):
        ae, filt = self.filteringSetup()
        ae(filt(None, {'title': ['one']}, ('+','id'), (None,None)), ['1'])
        ae(filt(None, {'title': ['issue']}, ('+','id'), (None,None)),
            ['1','2','3'])
        ae(filt(None, {'title': ['one', 'two']}, ('+','id'), (None,None)),
            ['1', '2'])

    def testFilteringLink(self):
        ae, filt = self.filteringSetup()
        ae(filt(None, {'status': '1'}, ('+','id'), (None,None)), ['2','3'])
        ae(filt(None, {'assignedto': '-1'}, ('+','id'), (None,None)), ['3','4'])

    def testFilteringRetired(self):
        ae, filt = self.filteringSetup()
        self.db.issue.retire('2')
        ae(filt(None, {'status': '1'}, ('+','id'), (None,None)), ['3'])

    def testFilteringMultilink(self):
        ae, filt = self.filteringSetup()
        ae(filt(None, {'nosy': '2'}, ('+','id'), (None,None)), ['3'])
        ae(filt(None, {'nosy': '-1'}, ('+','id'), (None,None)), ['1', '2'])

    def testFilteringMany(self):
        ae, filt = self.filteringSetup()
        ae(filt(None, {'nosy': '2', 'status': '1'}, ('+','id'), (None,None)),
            ['3'])

    def testFilteringRange(self):
        ae, filt = self.filteringSetup()
        # Date ranges
        ae(filt(None, {'deadline': 'from 2003-02-10 to 2003-02-23'}), ['2','3'])
        ae(filt(None, {'deadline': '2003-02-10; 2003-02-23'}), ['2','3'])
        ae(filt(None, {'deadline': '; 2003-02-16'}), ['1'])
        # Lets assume people won't invent a time machine, otherwise this test
        # may fail :)
        ae(filt(None, {'deadline': 'from 2003-02-16'}), ['2', '3', '4'])
        ae(filt(None, {'deadline': '2003-02-16;'}), ['2', '3', '4'])
        # year and month granularity
        ae(filt(None, {'deadline': '2002'}), [])
        ae(filt(None, {'deadline': '2003'}), ['1', '2', '3'])
        ae(filt(None, {'deadline': '2004'}), ['4'])
        ae(filt(None, {'deadline': '2003-02'}), ['2', '3'])
        ae(filt(None, {'deadline': '2003-03'}), [])
        ae(filt(None, {'deadline': '2003-02-16'}), ['2'])
        ae(filt(None, {'deadline': '2003-02-17'}), [])
        # Interval ranges
        ae(filt(None, {'foo': 'from 0:50 to 2:00'}), ['1'])
        ae(filt(None, {'foo': 'from 0:50 to 1d 2:00'}), ['1', '2'])
        ae(filt(None, {'foo': 'from 5:50'}), ['2'])
        ae(filt(None, {'foo': 'to 0:05'}), [])

    def testFilteringIntervalSort(self):
        # 1: '1:10'
        # 2: '1d'
        # 3: None
        # 4: '0:10'
        ae, filt = self.filteringSetup()
        # ascending should sort None, 1:10, 1d
        ae(filt(None, {}, ('+','foo'), (None,None)), ['3', '4', '1', '2'])
        # descending should sort 1d, 1:10, None
        ae(filt(None, {}, ('-','foo'), (None,None)), ['2', '1', '4', '3'])

    def testFilteringMultilinkSort(self):
        # 1: []
        # 2: []
        # 3: ['1','2']
        # 4: ['1']
        ae, filt = self.filteringSetup()
        ae(filt(None, {}, ('+','nosy'), (None,None)), ['1', '2', '4', '3'])
        ae(filt(None, {}, ('-','nosy'), (None,None)), ['3', '4', '1', '2'])

    def testFilteringDateSort(self):
        # '1': '2003-01-01.00:00'
        # '2': '2003-02-16.22:50'
        # '3': '2003-02-18'
        # '4': '2004-03-08'
        ae, filt = self.filteringSetup()
        # ascending
        ae(filt(None, {}, ('+','deadline'), (None,None)), ['1', '2', '3', '4'])
        # descending
        ae(filt(None, {}, ('-','deadline'), (None,None)), ['4', '3', '2', '1'])

    def testFilteringDateSortPriorityGroup(self):
        # '1': '2003-01-01.00:00'  1 => 2
        # '2': '2003-02-16.22:50'  3 => 1
        # '3': '2003-02-18'        2 => 3
        # '4': '2004-03-08'        1 => 2
        ae, filt = self.filteringSetup()
        # ascending
        ae(filt(None, {}, ('+','deadline'), ('+','priority')),
            ['2', '1', '4', '3'])
        ae(filt(None, {}, ('-','deadline'), ('+','priority')),
            ['2', '4', '1', '3'])
        # descending
        ae(filt(None, {}, ('+','deadline'), ('-','priority')),
            ['3', '1', '4', '2'])
        ae(filt(None, {}, ('-','deadline'), ('-','priority')),
            ['3', '4', '1', '2'])

# XXX add sorting tests for other types
# XXX test auditors and reactors

    def testImportExport(self):
        # use the filtering setup to create a bunch of items
        ae, filt = self.filteringSetup()
        self.db.user.retire('3')
        self.db.issue.retire('2')

        # grab snapshot of the current database
        orig = {}
        for cn,klass in self.db.classes.items():
            cl = orig[cn] = {}
            for id in klass.list():
                it = cl[id] = {}
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

            # shut down this db and nuke it
            self.db.close()
            self.nuke_database()

            # open a new, empty database
            os.makedirs(config.DATABASE + '/files')
            self.db = self.module.Database(config, 'admin')
            setupSchema(self.db, 0, self.module)

            # import
            for cn, items in export.items():
                klass = self.db.classes[cn]
                names = items[0]
                maxid = 1
                for itemprops in items[1:]:
                    id = int(klass.import_list(names, itemprops))
                    if hasattr(klass, 'import_files'):
                        klass.import_files('_test_export', id)
                    maxid = max(maxid, id)
                self.db.setid(cn, str(maxid+1))
                klass.import_journals(journals[cn])
        finally:
            shutil.rmtree('_test_export')

        # compare with snapshot of the database
        for cn, items in orig.items():
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

        # make sure the retired items are actually imported
        ae(self.db.user.get('4', 'username'), 'blop')
        ae(self.db.issue.get('2', 'title'), 'issue two')

        # make sure id counters are set correctly
        maxid = max([int(id) for id in self.db.user.list()])
        newid = self.db.user.create(username='testing')
        assert newid > maxid

    def testSafeGet(self):
        # existent nodeid, existent property
        self.assertEqual(self.db.user.safeget('1', 'username'), 'admin')
        # nonexistent nodeid, existent property
        self.assertEqual(self.db.user.safeget('999', 'username'), None)
        # different default
        self.assertEqual(self.db.issue.safeget('999', 'nosy', []), [])

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
            'creator', 'deadline', 'files', 'fixer', 'foo', 'id', 'messages',
            'nosy', 'priority', 'status', 'superseder', 'title'])
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
            'creator', 'deadline', 'files', 'foo', 'id', 'messages',
            'nosy', 'priority', 'status', 'superseder'])
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
            'creator', 'deadline', 'files', 'fixer', 'foo', 'id', 'messages',
            'nosy', 'priority', 'status', 'superseder'])
        self.assertEqual(self.db.issue.list(), ['1'])

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
        self.db = self.module.Database(config, 'admin')
        self.assertRaises(ValueError, self.module.Class, self.db, "a",
            creation=String())
        self.assertRaises(ValueError, self.module.Class, self.db, "a",
            activity=String())
        self.assertRaises(ValueError, self.module.Class, self.db, "a",
            creator=String())
        self.assertRaises(ValueError, self.module.Class, self.db, "a",
            actor=String())

    def init_a(self):
        self.db = self.module.Database(config, 'admin')
        a = self.module.Class(self.db, "a", name=String())
        a.setkey("name")
        self.db.post_init()

    def init_ab(self):
        self.db = self.module.Database(config, 'admin')
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
        self.db = self.module.Database(config, 'admin')
        a = self.module.Class(self.db, "a", name=String(), fooz=String())
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
        self.assertEqual(self.db.a.get(aid, 'fooz'), None)
        self.assertEqual(self.db.b.get(aid, 'name'), 'bear')
        aid2 = self.db.a.create(name='aardvark', fooz='booz')
        self.db.commit(); self.db.close()

        # test
        self.init_amod()
        self.assertEqual(self.db.a.get(aid, 'name'), 'apple')
        self.assertEqual(self.db.a.get(aid, 'fooz'), None)
        self.assertEqual(self.db.b.get(aid, 'name'), 'bear')
        self.assertEqual(self.db.a.get(aid2, 'name'), 'aardvark')
        self.assertEqual(self.db.a.get(aid2, 'fooz'), 'booz')

        # confirm journal's ok
        self.db.getjournal('a', aid)
        self.db.getjournal('a', aid2)

    def init_amodkey(self):
        self.db = self.module.Database(config, 'admin')
        a = self.module.Class(self.db, "a", name=String(), fooz=String())
        a.setkey("fooz")
        b = self.module.Class(self.db, "b", name=String())
        b.setkey("name")
        self.db.post_init()

    def test_changeClassKey(self):
        self.init_amod()
        aid = self.db.a.create(name='apple')
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.db.commit(); self.db.close()

        # change the key to fooz on a
        self.init_amodkey()
        self.assertEqual(self.db.a.get(aid, 'name'), 'apple')
        self.assertEqual(self.db.a.get(aid, 'fooz'), None)
        self.assertRaises(KeyError, self.db.a.lookup, 'apple')
        aid2 = self.db.a.create(name='aardvark', fooz='booz')
        self.db.commit(); self.db.close()

        # check
        self.init_amodkey()
        self.assertEqual(self.db.a.lookup('booz'), aid2)

        # confirm journal's ok
        self.db.getjournal('a', aid)

    def init_amodml(self):
        self.db = self.module.Database(config, 'admin')
        a = self.module.Class(self.db, "a", name=String(),
            fooz=Multilink('a'))
        a.setkey('name')
        self.db.post_init()

    def test_makeNewMultilink(self):
        self.init_a()
        aid = self.db.a.create(name='apple')
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.db.commit(); self.db.close()

        # add a multilink prop
        self.init_amodml()
        bid = self.db.a.create(name='bear', fooz=[aid])
        self.assertEqual(self.db.a.find(fooz=aid), [bid])
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.db.commit(); self.db.close()

        # check
        self.init_amodml()
        self.assertEqual(self.db.a.find(fooz=aid), [bid])
        self.assertEqual(self.db.a.lookup('apple'), aid)
        self.assertEqual(self.db.a.lookup('bear'), bid)

        # confirm journal's ok
        self.db.getjournal('a', aid)
        self.db.getjournal('a', bid)

    def test_removeMultilink(self):
        # add a multilink prop
        self.init_amodml()
        aid = self.db.a.create(name='apple')
        bid = self.db.a.create(name='bear', fooz=[aid])
        self.assertEqual(self.db.a.find(fooz=aid), [bid])
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
    ''' tests specific to RDBMS backends '''
    def test_indexTest(self):
        self.assertEqual(self.db.sql_index_exists('_issue', '_issue_id_idx'), 1)
        self.assertEqual(self.db.sql_index_exists('_issue', '_issue_x_idx'), 0)


class ClassicInitTest(unittest.TestCase):
    count = 0
    db = None
    extra_config = ''

    def setUp(self):
        ClassicInitTest.count = ClassicInitTest.count + 1
        self.dirname = '_test_init_%s'%self.count
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def testCreation(self):
        ae = self.assertEqual

        # create the instance
        init.install(self.dirname, 'templates/classic')
        init.write_select_db(self.dirname, self.backend)

        if self.extra_config:
            f = open(os.path.join(self.dirname, 'config.py'), 'a')
            try:
                f.write(self.extra_config)
            finally:
                f.close()
        
        init.initialise(self.dirname, 'sekrit')

        # check we can load the package
        instance = imp.load_package(self.dirname, self.dirname)

        # and open the database
        db = self.db = instance.open()

        # check the basics of the schema and initial data set
        l = db.priority.list()
        ae(l, ['1', '2', '3', '4', '5'])
        l = db.status.list()
        ae(l, ['1', '2', '3', '4', '5', '6', '7', '8'])
        l = db.keyword.list()
        ae(l, [])
        l = db.user.list()
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

