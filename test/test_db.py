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
# $Id: test_db.py,v 1.92 2003-10-07 08:52:12 richard Exp $ 

import unittest, os, shutil, time

from roundup.hyperdb import String, Password, Link, Multilink, Date, \
    Interval, DatabaseError, Boolean, Number, Node
from roundup import date, password
from roundup.indexer import Indexer

def setupSchema(db, create, module):
    status = module.Class(db, "status", name=String())
    status.setkey("name")
    user = module.Class(db, "user", username=String(), password=Password(),
        assignable=Boolean(), age=Number(), roles=String())
    user.setkey("username")
    file = module.FileClass(db, "file", name=String(), type=String(),
        comment=String(indexme="yes"), fooz=Password())
    issue = module.IssueClass(db, "issue", title=String(indexme="yes"),
        status=Link("status"), nosy=Multilink("user"), deadline=Date(),
        foo=Interval(), files=Multilink("file"), assignedto=Link('user'))
    session = module.Class(db, 'session', title=String())
    session.disableJournalling()
    db.post_init()
    if create:
        user.create(username="admin", roles='Admin')
        status.create(name="unread")
        status.create(name="in-progress")
        status.create(name="testing")
        status.create(name="resolved")
    db.commit()

class MyTestCase(unittest.TestCase):
    def tearDown(self):
        self.db.close()
        if os.path.exists('_test_dir'):
            shutil.rmtree('_test_dir')

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

    # Mysql connection data
    MYSQL_DBHOST = 'localhost'
    MYSQL_DBUSER = 'rounduptest'
    MYSQL_DBPASSWORD = 'rounduptest'
    MYSQL_DBNAME = 'rounduptest'
    MYSQL_DATABASE = (MYSQL_DBHOST, MYSQL_DBUSER, MYSQL_DBPASSWORD, MYSQL_DBNAME)

    # Postgresql connection data
    POSTGRESQL_DBHOST = 'localhost'
    POSTGRESQL_DBUSER = 'rounduptest'
    POSTGRESQL_DBPASSWORD = 'rounduptest'
    POSTGRESQL_DBNAME = 'rounduptest'
    POSTGRESQL_PORT = 5432
    POSTGRESQL_DATABASE = {'host': POSTGRESQL_DBHOST, 'port': POSTGRESQL_PORT,
        'user': POSTGRESQL_DBUSER, 'password': POSTGRESQL_DBPASSWORD,
        'database': POSTGRESQL_DBNAME}

class nodbconfig(config):
    MYSQL_DATABASE = (config.MYSQL_DBHOST, config.MYSQL_DBUSER, config.MYSQL_DBPASSWORD)

class anydbmDBTestCase(MyTestCase):
    def setUp(self):
        from roundup.backends import anydbm
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = anydbm.Database(config, 'admin')
        setupSchema(self.db, 1, anydbm)

    #
    # schema mutation
    #
    def testAddProperty(self):
        self.db.issue.create(title="spam", status='1')
        self.db.commit()

        self.db.issue.addprop(fixer=Link("user"))
        # force any post-init stuff to happen
        self.db.post_init()
        props = self.db.issue.getprops()
        keys = props.keys()
        keys.sort()
        self.assertEqual(keys, ['activity', 'assignedto', 'creation',
            'creator', 'deadline', 'files', 'fixer', 'foo', 'id', 'messages',
            'nosy', 'status', 'superseder', 'title'])
        self.assertEqual(self.db.issue.get('1', "fixer"), None)

    def testRemoveProperty(self):
        self.db.issue.create(title="spam", status='1')
        self.db.commit()

        del self.db.issue.properties['title']
        self.db.post_init()
        props = self.db.issue.getprops()
        keys = props.keys()
        keys.sort()
        self.assertEqual(keys, ['activity', 'assignedto', 'creation',
            'creator', 'deadline', 'files', 'foo', 'id', 'messages',
            'nosy', 'status', 'superseder'])
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
        self.assertEqual(keys, ['activity', 'assignedto', 'creation',
            'creator', 'deadline', 'files', 'fixer', 'foo', 'id', 'messages',
            'nosy', 'status', 'superseder'])
        self.assertEqual(self.db.issue.list(), ['1'])

    #
    # basic operations
    #
    def testIDGeneration(self):
        id1 = self.db.issue.create(title="spam", status='1')
        id2 = self.db.issue.create(title="eggs", status='2')
        self.assertNotEqual(id1, id2)

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

    def testLinkChange(self):
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

    def testMultilinkChange(self):
        for commit in (0,1):
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
            self.assertEqual(self.db.issue.get(nid, "nosy"), [u1,u2])

    def testDateChange(self):
        for commit in (0,1):
            nid = self.db.issue.create(title="spam", status='1')
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

    def testIntervalChange(self):
        for commit in (0,1):
            nid = self.db.issue.create(title="spam", status='1')
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

    def testBooleanChange(self):
        userid = self.db.user.create(username='foo', assignable=1)
        self.assertEqual(1, self.db.user.get(userid, 'assignable'))
        self.db.user.set(userid, assignable=0)
        self.assertEqual(self.db.user.get(userid, 'assignable'), 0)

    def testBooleanUnset(self):
        nid = self.db.user.create(username='foo', assignable=1)
        self.db.user.set(nid, assignable=None)
        self.assertEqual(self.db.user.get(nid, "assignable"), None)

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

    def testKeyValue(self):
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

    def testRetire(self):
        self.db.issue.create(title="spam", status='1')
        b = self.db.status.get('1', 'name')
        a = self.db.status.list()
        self.db.status.retire('1')
        # make sure the list is different 
        self.assertNotEqual(a, self.db.status.list())
        # can still access the node if necessary
        self.assertEqual(self.db.status.get('1', 'name'), b)
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
        klass.destroy(newid)
        self.assertRaises(IndexError, klass.get, newid, 'title')
        self.assertNotEqual(len(klass.list()), n)
        if klass.do_journal:
            self.assertRaises(IndexError, klass.history, newid)

        # now with a commit
        newid = klass.create(title='Mr Friendly')
        n = len(klass.list())
        self.assertEqual(klass.get(newid, 'title'), 'Mr Friendly')
        self.db.commit()
        klass.destroy(newid)
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
        klass.destroy(newid)
        self.assertNotEqual(len(klass.list()), n)
        self.assertRaises(IndexError, klass.get, newid, 'title')
        self.db.rollback()
        self.assertEqual(klass.get(newid, 'title'), 'Mr Friendly')
        self.assertEqual(len(klass.list()), n)
        if klass.do_journal:
            self.assertNotEqual(klass.history(newid), [])

    def testExceptions(self):
        # this tests the exceptions that should be raised
        ar = self.assertRaises

        #
        # class create
        #
        # string property
        ar(TypeError, self.db.status.create, name=1)
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
        time.sleep(1)
        entry = self.db.getjournal('issue', '1')[-1]
        (x, date_stamp, x, x, x) = entry
        self.db.issue.disableJournalling()
        self.db.issue.set('1', title='hello world')
        self.db.commit()
        entry = self.db.getjournal('issue', '1')[-1]
        (x, date_stamp2, x, x, x) = entry
        # see if the change was journalled when it shouldn't have been
        self.assertEqual(date_stamp, date_stamp2)
        time.sleep(1)
        self.db.issue.enableJournalling()
        self.db.issue.set('1', title='hello world 2')
        self.db.commit()
        entry = self.db.getjournal('issue', '1')[-1]
        (x, date_stamp2, x, x, x) = entry
        # see if the change was journalled
        self.assertNotEqual(date_stamp, date_stamp2)

    def testJournalPreCommit(self):
        id = self.db.user.create(username="mary")
        self.assertEqual(len(self.db.getjournal('user', id)), 1)
        self.db.commit()

    def testPack(self):
        id = self.db.issue.create(title="spam", status='1')
        self.db.commit()
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

    def testSearching(self):
        self.db.file.create(content='hello', type="text/plain")
        self.db.file.create(content='world', type="text/frozz",
            comment='blah blah')
        self.db.issue.create(files=['1', '2'], title="flebble plop")
        self.db.issue.create(title="flebble frooz")
        self.db.commit()
        self.assertEquals(self.db.indexer.search(['hello'], self.db.issue),
            {'1': {'files': ['1']}})
        self.assertEquals(self.db.indexer.search(['world'], self.db.issue), {})
        self.assertEquals(self.db.indexer.search(['frooz'], self.db.issue),
            {'2': {}})
        self.assertEquals(self.db.indexer.search(['flebble'], self.db.issue),
            {'2': {}, '1': {}})

    def testReindexing(self):
        self.db.issue.create(title="frooz")
        self.db.commit()
        self.assertEquals(self.db.indexer.search(['frooz'], self.db.issue),
            {'1': {}})
        self.db.issue.set('1', title="dooble")
        self.db.commit()
        self.assertEquals(self.db.indexer.search(['dooble'], self.db.issue),
            {'1': {}})
        self.assertEquals(self.db.indexer.search(['frooz'], self.db.issue), {})

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
    def testFind(self):
        self.db.user.create(username='test')
        ids = []
        ids.append(self.db.issue.create(status="1", nosy=['1']))
        oddid = self.db.issue.create(status="2", nosy=['2'], assignedto='2')
        ids.append(self.db.issue.create(status="1", nosy=['1','2']))
        self.db.issue.create(status="3", nosy=['1'], assignedto='1')
        ids.sort()

        # should match first and third
        got = self.db.issue.find(status='1')
        got.sort()
        self.assertEqual(got, ids)

        # none
        self.assertEqual(self.db.issue.find(status='4'), [])

        # should match first and third
        got = self.db.issue.find(assignedto=None)
        got.sort()
        self.assertEqual(got, ids)

        # should match first three
        got = self.db.issue.find(status='1', nosy='2')
        got.sort()
        ids.append(oddid)
        ids.sort()
        self.assertEqual(got, ids)

        # none
        self.assertEqual(self.db.issue.find(status='4', nosy='3'), [])

    def testStringFind(self):
        ids = []
        ids.append(self.db.issue.create(title="spam"))
        self.db.issue.create(title="not spam")
        ids.append(self.db.issue.create(title="spam"))
        ids.sort()
        got = self.db.issue.stringFind(title='spam')
        got.sort()
        self.assertEqual(got, ids)
        self.assertEqual(self.db.issue.stringFind(title='fubar'), [])

    def filteringSetup(self):
        for user in (
                {'username': 'bleep'},
                {'username': 'blop'},
                {'username': 'blorp'}):
            self.db.user.create(**user)
        iss = self.db.issue
        for issue in (
                {'title': 'issue one', 'status': '2',
                    'foo': date.Interval('1:10'), 
                    'deadline': date.Date('2003-01-01.00:00')},
                {'title': 'issue two', 'status': '1',
                    'foo': date.Interval('1d'), 
                    'deadline': date.Date('2003-02-16.22:50')},
                {'title': 'issue three', 'status': '1',
                    'nosy': ['1','2'], 'deadline': date.Date('2003-02-18')},
                {'title': 'non four', 'status': '3',
                    'foo': date.Interval('0:10'), 
                    'nosy': ['1'], 'deadline': date.Date('2004-03-08')}):
            self.db.issue.create(**issue)
        self.db.commit()
        return self.assertEqual, self.db.issue.filter

    def testFilteringID(self):
        ae, filt = self.filteringSetup()
        ae(filt(None, {'id': '1'}, ('+','id'), (None,None)), ['1'])

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
        ae, filt = self.filteringSetup()
        # ascending should sort None, 1:10, 1d
        ae(filt(None, {}, ('+','foo'), (None,None)), ['3', '4', '1', '2'])
        # descending should sort 1d, 1:10, None
        ae(filt(None, {}, ('-','foo'), (None,None)), ['2', '1', '4', '3'])

# XXX add sorting tests for other types
# XXX test auditors and reactors

class anydbmReadOnlyDBTestCase(MyTestCase):
    def setUp(self):
        from roundup.backends import anydbm
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        db = anydbm.Database(config, 'admin')
        setupSchema(db, 1, anydbm)
        db.close()
        self.db = anydbm.Database(config)
        setupSchema(self.db, 0, anydbm)

    def testExceptions(self):
        # this tests the exceptions that should be raised
        ar = self.assertRaises

        # this tests the exceptions that should be raised
        ar(DatabaseError, self.db.status.create, name="foo")
        ar(DatabaseError, self.db.status.set, '1', name="foo")
        ar(DatabaseError, self.db.status.retire, '1')


class bsddbDBTestCase(anydbmDBTestCase):
    def setUp(self):
        from roundup.backends import bsddb
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = bsddb.Database(config, 'admin')
        setupSchema(self.db, 1, bsddb)

class bsddbReadOnlyDBTestCase(anydbmReadOnlyDBTestCase):
    def setUp(self):
        from roundup.backends import bsddb
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        db = bsddb.Database(config, 'admin')
        setupSchema(db, 1, bsddb)
        db.close()
        self.db = bsddb.Database(config)
        setupSchema(self.db, 0, bsddb)


class bsddb3DBTestCase(anydbmDBTestCase):
    def setUp(self):
        from roundup.backends import bsddb3
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = bsddb3.Database(config, 'admin')
        setupSchema(self.db, 1, bsddb3)

class bsddb3ReadOnlyDBTestCase(anydbmReadOnlyDBTestCase):
    def setUp(self):
        from roundup.backends import bsddb3
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        db = bsddb3.Database(config, 'admin')
        setupSchema(db, 1, bsddb3)
        db.close()
        self.db = bsddb3.Database(config)
        setupSchema(self.db, 0, bsddb3)


class mysqlDBTestCase(anydbmDBTestCase):
    def setUp(self):
        from roundup.backends import mysql
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        # open database for testing
        self.db = mysql.Database(config, 'admin')       
        setupSchema(self.db, 1, mysql)
         
    def tearDown(self):
        from roundup.backends import mysql
        self.db.close()
        mysql.Database.nuke(config)

class mysqlReadOnlyDBTestCase(anydbmReadOnlyDBTestCase):
    def setUp(self):
        from roundup.backends import mysql
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = mysql.Database(config)
        setupSchema(self.db, 0, mysql)

    def tearDown(self):
        from roundup.backends import mysql
        self.db.close()
        mysql.Database.nuke(config)

class postgresqlDBTestCase(anydbmDBTestCase):
    def setUp(self):
        from roundup.backends import postgresql
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        # open database for testing
        self.db = postgresql.Database(config, 'admin')       
        setupSchema(self.db, 1, mysql)
         
    def tearDown(self):
        from roundup.backends import postgresql
        self.db.close()
        postgresql.Database.nuke(config)

class postgresqlReadOnlyDBTestCase(anydbmReadOnlyDBTestCase):
    def setUp(self):
        from roundup.backends import postgresql
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = postgresql.Database(config)
        setupSchema(self.db, 0, mysql)

    def tearDown(self):
        from roundup.backends import postgresql
        self.db.close()
        postgresql.Database.nuke(config)

class sqliteDBTestCase(anydbmDBTestCase):
    def setUp(self):
        from roundup.backends import sqlite
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = sqlite.Database(config, 'admin')
        setupSchema(self.db, 1, sqlite)

class sqliteReadOnlyDBTestCase(anydbmReadOnlyDBTestCase):
    def setUp(self):
        from roundup.backends import sqlite
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        db = sqlite.Database(config, 'admin')
        setupSchema(db, 1, sqlite)
        db.close()
        self.db = sqlite.Database(config)
        setupSchema(self.db, 0, sqlite)


class metakitDBTestCase(anydbmDBTestCase):
    def setUp(self):
        from roundup.backends import metakit
        import weakref
        metakit._instances = weakref.WeakValueDictionary()
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = metakit.Database(config, 'admin')
        setupSchema(self.db, 1, metakit)

    def testTransactions(self):
        # remember the number of items we started
        num_issues = len(self.db.issue.list())
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
        num_files = len(self.db.file.list())
        for i in range(10):
            self.db.file.create(name="test", type="text/plain", 
                    content="hi %d"%(i))
            self.db.commit()
        # TODO: would be good to be able to ensure the file is not on disk after
        # a rollback...
        num_files2 = len(self.db.file.list())
        self.assertNotEqual(num_files, num_files2)
        self.db.file.create(name="test", type="text/plain", content="hi")
        num_rfiles = len(os.listdir(self.db.config.DATABASE + '/files/file/0'))
        self.db.rollback()
        num_rfiles2 = len(os.listdir(self.db.config.DATABASE + '/files/file/0'))
        self.assertEqual(num_files2, len(self.db.file.list()))
        self.assertEqual(num_rfiles2, num_rfiles-1)

    def testBooleanUnset(self):
        # XXX: metakit can't unset Booleans :(
        nid = self.db.user.create(username='foo', assignable=1)
        self.db.user.set(nid, assignable=None)
        self.assertEqual(self.db.user.get(nid, "assignable"), 0)

    def testNumberUnset(self):
        # XXX: metakit can't unset Numbers :(
        nid = self.db.user.create(username='foo', age=1)
        self.db.user.set(nid, age=None)
        self.assertEqual(self.db.user.get(nid, "age"), 0)

class metakitReadOnlyDBTestCase(anydbmReadOnlyDBTestCase):
    def setUp(self):
        from roundup.backends import metakit
        import weakref
        metakit._instances = weakref.WeakValueDictionary()
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        db = metakit.Database(config, 'admin')
        setupSchema(db, 1, metakit)
        db.close()
        self.db = metakit.Database(config)
        setupSchema(self.db, 0, metakit)

def suite():
    p = []

    l = [
    #     unittest.makeSuite(anydbmDBTestCase, 'test'),
    #     unittest.makeSuite(anydbmReadOnlyDBTestCase, 'test')
    ]
    p.append('anydbm')
#    return unittest.TestSuite(l)

    from roundup import backends

    if hasattr(backends, 'mysql'):
        from roundup.backends import mysql
        try:
            # Check if we can run mysql tests
            import MySQLdb
            db = mysql.Database(nodbconfig, 'admin')
            db.conn.select_db(config.MYSQL_DBNAME)
            db.sql("SHOW TABLES");
            tables = db.sql_fetchall()
            if tables:
                # Database should be empty. We don't dare to delete any data
                raise DatabaseError, "(Database %s contains tables)" % config.MYSQL_DBNAME
            db.sql("DROP DATABASE %s" % config.MYSQL_DBNAME)
            db.sql("CREATE DATABASE %s" % config.MYSQL_DBNAME)
            db.close()
        except (MySQLdb.ProgrammingError, DatabaseError), msg:
            print "Warning! Mysql tests will not be performed", msg
            print "See doc/mysql.txt for more details."
        else:
            p.append('mysql')
            l.append(unittest.makeSuite(mysqlDBTestCase, 'test'))
            l.append(unittest.makeSuite(mysqlReadOnlyDBTestCase, 'test'))
#    return unittest.TestSuite(l)

    if hasattr(backends, 'postgresql'):
        from roundup.backends import postgresql
        try:
            # Check if we can run mysql tests
            import psycopg
            db = psycopg.Database(nodbconfig, 'admin')
            db.conn.select_db(config.POSTGRESQL_DBNAME)
            db.sql("SHOW TABLES");
            tables = db.sql_fetchall()
            if tables:
                # Database should be empty. We don't dare to delete any data
                raise DatabaseError, "(Database %s contains tables)"%config.POSTGRESQL_DBNAME
            db.sql("DROP DATABASE %s" % config.POSTGRESQL_DBNAME)
            db.sql("CREATE DATABASE %s" % config.POSTGRESQL_DBNAME)
            db.close()
        except (MySQLdb.ProgrammingError, DatabaseError), msg:
            print "Warning! Postgresql tests will not be performed", msg
            print "See doc/postgresql.txt for more details."
        else:
            p.append('postgresql')
            l.append(unittest.makeSuite(postgresqlDBTestCase, 'test'))
            l.append(unittest.makeSuite(postgresqlReadOnlyDBTestCase, 'test'))
    #return unittest.TestSuite(l)

    if hasattr(backends, 'sqlite'):
        p.append('sqlite')
        l.append(unittest.makeSuite(sqliteDBTestCase, 'test'))
        l.append(unittest.makeSuite(sqliteReadOnlyDBTestCase, 'test'))

    if hasattr(backends, 'bsddb'):
        p.append('bsddb')
        l.append(unittest.makeSuite(bsddbDBTestCase, 'test'))
        l.append(unittest.makeSuite(bsddbReadOnlyDBTestCase, 'test'))

    if hasattr(backends, 'bsddb3'):
        p.append('bsddb3')
        l.append(unittest.makeSuite(bsddb3DBTestCase, 'test'))
        l.append(unittest.makeSuite(bsddb3ReadOnlyDBTestCase, 'test'))

    if hasattr(backends, 'metakit'):
        p.append('metakit')
        l.append(unittest.makeSuite(metakitDBTestCase, 'test'))
        l.append(unittest.makeSuite(metakitReadOnlyDBTestCase, 'test'))

    print 'running %s backend tests'%(', '.join(p))
    return unittest.TestSuite(l)

# vim: set filetype=python ts=4 sw=4 et si
