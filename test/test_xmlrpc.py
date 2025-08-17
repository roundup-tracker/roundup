#
# Copyright (C) 2007 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

from __future__ import print_function
import unittest, os, shutil, errno, pytest, sys, difflib, re

from contextlib import contextmanager 

from roundup.anypy import xmlrpc_
MultiCall = xmlrpc_.client.MultiCall
from roundup.cgi.exceptions import *
from roundup import init, instance, password, hyperdb, date
from roundup.xmlrpc import RoundupInstance, RoundupDispatcher
from roundup.backends import list_backends
from roundup.hyperdb import String
from roundup.cgi import TranslationService
from roundup.test.tx_Source_detector import init as tx_Source_init

from . import db_test_base
from .test_mysql import skip_mysql
from .test_postgresql import skip_postgresql

from .pytest_patcher import mark_class
from roundup.anypy.xmlrpc_ import client

if client.defusedxml:
    skip_defusedxml = lambda func, *args, **kwargs: func
else:
    skip_defusedxml = mark_class(pytest.mark.skip(
        reason='Skipping defusedxml tests: defusedxml library not available'))

if sys.version_info[0] > 2:
    skip_python2 = lambda func, *args, **kwargs: func
else:
    skip_python2 = mark_class(pytest.mark.skip(
        reason='Skipping test under python 2'))

@contextmanager
def disable_defusedxml():
    # if defusedxml not loaded, do nothing
    if 'defusedxml' not in sys.modules:
        yield
        return

    sys.modules['defusedxml'].xmlrpc.unmonkey_patch()
    try:
        yield
    finally:
        # restore normal defused xmlrpc functions
        sys.modules['defusedxml'].xmlrpc.monkey_patch()

class XmlrpcTest(object):

    backend = None

    def setUp(self):
        self.dirname = '_test_xmlrpc'
        # set up and open a tracker
        self.instance = db_test_base.setupTracker(self.dirname, self.backend)

        # open the database
        self.db = self.instance.open('admin')

        print("props_only default", self.db.security.get_props_only_default())

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

        tx_Source_init(self.db)

        self.server = RoundupInstance(self.db, self.instance.actions, None)

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError as error:
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

    def testSchema(self):
        schema={'status': [('name', '<roundup.hyperdb.String>'),
                           ('order', '<roundup.hyperdb.Number>')],
                'keyword': [('name', '<roundup.hyperdb.String>')],
                'priority': [('name', '<roundup.hyperdb.String>'),
                             ('order', '<roundup.hyperdb.Number>')],
                'user': [('address', '<roundup.hyperdb.String>'),
                         ('alternate_addresses', '<roundup.hyperdb.String>'),
                         ('organisation', '<roundup.hyperdb.String>'),
                         ('password', '<roundup.hyperdb.Password>'),
                         ('phone', '<roundup.hyperdb.String>'),
                         ('queries', '<roundup.hyperdb.Multilink to "query">'),
                         ('realname', '<roundup.hyperdb.String>'),
                         ('roles', '<roundup.hyperdb.String>'),
                         ('timezone', '<roundup.hyperdb.String>'),
                         ('username', '<roundup.hyperdb.String>')],
                'file': [('content', '<roundup.hyperdb.String>'),
                         ('name', '<roundup.hyperdb.String>'),
                         ('type', '<roundup.hyperdb.String>')],
                'msg': [('author', '<roundup.hyperdb.Link to "user">'),
                        ('content', '<roundup.hyperdb.String>'),
                        ('date', '<roundup.hyperdb.Date>'),
                        ('files', '<roundup.hyperdb.Multilink to "file">'),
                        ('inreplyto', '<roundup.hyperdb.String>'),
                        ('messageid', '<roundup.hyperdb.String>'),
                        ('recipients', '<roundup.hyperdb.Multilink to "user">'),
                        ('summary', '<roundup.hyperdb.String>'),
                        ('tx_Source', '<roundup.hyperdb.String>'),
                        ('type', '<roundup.hyperdb.String>')],
                'query': [('klass', '<roundup.hyperdb.String>'),
                          ('name', '<roundup.hyperdb.String>'),
                          ('private_for', '<roundup.hyperdb.Link to "user">'),
                          ('url', '<roundup.hyperdb.String>')],
                'issue': [('assignedto', '<roundup.hyperdb.Link to "user">'),
                          ('files', '<roundup.hyperdb.Multilink to "file">'),
                          ('keyword', '<roundup.hyperdb.Multilink to "keyword">'),
                          ('messages', '<roundup.hyperdb.Multilink to "msg">'), 
                          ('nosy', '<roundup.hyperdb.Multilink to "user">'),
                          ('priority', '<roundup.hyperdb.Link to "priority">'),
                          ('status', '<roundup.hyperdb.Link to "status">'),
                          ('superseder', '<roundup.hyperdb.Multilink to "issue">'),
                          ('title', '<roundup.hyperdb.String>'),
                          ('tx_Source', '<roundup.hyperdb.String>')]}

        results = self.server.schema()
        self.assertEqual(results, schema)

    def testLookup(self):
        self.assertRaises(KeyError, self.server.lookup, 'user', '1')
        results = self.server.lookup('user', 'admin')
        self.assertEqual(results, '1')

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

        # test a bogus action
        with self.assertRaises(Exception) as cm:
            self.server.action('bogus')
        print(cm.exception)
        self.assertEqual(cm.exception.args[0],
                         'action "bogus" is not supported ')

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
            except Unauthorised as err:
                self.fail('raised %s'%err)
        finally:
            self.db.setCurrentUser('joe')

    def testAuthAllowedCreate(self):
        self.db.setCurrentUser('admin')
        try:
            try:
                self.server.create('user', 'username=blah')
            except Unauthorised as err:
                self.fail('raised %s'%err)
        finally:
            self.db.setCurrentUser('joe')

    def testAuthFilter(self):
        # this checks if we properly check for search permissions
        self.db.security.permissions = {}
        # self.db.security.set_props_only_default(props_only=False)
        self.db.security.addRole(name='User')
        self.db.security.addRole(name='Project')
        self.db.security.addPermissionToRole('User', 'Web Access')
        self.db.security.addPermissionToRole('Project', 'Web Access')
        # Allow viewing keyword
        p = self.db.security.addPermission(name='View', klass='keyword')
        print("View keyword class: %r"%p)
        self.db.security.addPermissionToRole('User', p)
        # Allow viewing interesting things (but not keyword) on issue
        # But users might only view issues where they are on nosy
        # (so in the real world the check method would be better)
        p = self.db.security.addPermission(name='View', klass='issue',
            properties=("title", "status"), check=lambda x,y,z: True)
        print("View keyword class w/ props: %r"%p)
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
        print("View issue class: %r"%p)
        self.db.security.addPermissionToRole('User', p)
        # Allow user to search for issue.status
        p = self.db.security.addPermission(name='Search', klass='issue',
            properties=("status",))
        print("View Search class w/ props: %r"%p)
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

    def testMulticall(self):
        translator = TranslationService.get_translation(
            language=self.instance.config["TRACKER_LANGUAGE"],
            tracker_home=self.instance.config["TRACKER_HOME"])
        self.server = RoundupDispatcher(self.db, self.instance.actions,
            translator, allow_none = True)
        class S:
            multicall=self.server.funcs['system.multicall']
        self.server.system = S()
        self.db.issue.create(title='i1')
        self.db.issue.create(title='i2')
        m = MultiCall(self.server)
        m.display('issue1')
        m.display('issue2')
        result = m()
        results = [
            {'files': [], 'status': '1', 'tx_Source': 'web',
             'keyword': [], 'title': 'i1', 'nosy': [], 'messages': [],
             'priority': None, 'assignedto': None, 'superseder': []},
            {'files': [], 'status': '1', 'tx_Source': 'web',
             'keyword': [], 'title': 'i2', 'nosy': [], 'messages': [],
             'priority': None, 'assignedto': None, 'superseder': []}]
        for n, r in enumerate(result):
            self.assertEqual(r, results[n])

    @skip_python2
    @skip_defusedxml
    def testDefusedXmlBomb(self):
        self.XmlBomb(expectIn=b"defusedxml.common.EntitiesForbidden")

    @skip_python2
    def testNonDefusedXmlBomb(self):
        with disable_defusedxml():
            self.XmlBomb(expectIn=b"1234567890"*511)

    def XmlBomb(self, expectIn=None):

        bombInput = """<?xml version='1.0'?>
        <!DOCTYPE xmlbomb [
        <!ENTITY a "1234567890" >
        <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">
        <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">
        <!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;">
        ]>
        <methodCall>
        <methodName>filter</methodName>
        <params>
        <param>
        <value><string>&d;</string></value>
        </param>
        <param>
        <value><array><data>
        <value><string>0</string></value>
        <value><string>2</string></value>
        <value><string>3</string></value>
        </data></array></value>
        </param>
        <param>
        <value><struct>
        <member>
        <name>username</name>
        <value><string>demo</string></value>
        </member>
        </struct></value>
        </param>
        </params>
        </methodCall>
        """
        translator = TranslationService.get_translation(
            language=self.instance.config["TRACKER_LANGUAGE"],
            tracker_home=self.instance.config["TRACKER_HOME"])
        self.server = RoundupDispatcher(self.db, self.instance.actions,
            translator, allow_none = True)
        response = self.server.dispatch(bombInput)
        print(response)
        self.assertIn(expectIn, response)

class anydbmXmlrpcTest(XmlrpcTest, unittest.TestCase):
    backend = 'anydbm'


@skip_mysql
class mysqlXmlrpcTest(XmlrpcTest, unittest.TestCase):
    backend = 'mysql'


class sqliteXmlrpcTest(XmlrpcTest, unittest.TestCase):
    backend = 'sqlite'


@skip_postgresql
class postgresqlXmlrpcTest(XmlrpcTest, unittest.TestCase):
    backend = 'postgresql'
