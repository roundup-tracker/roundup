import pytest
import unittest
import os
import shutil
import errno
import cgi

from time import sleep
from datetime import datetime, timedelta
from roundup.test.tx_Source_detector import init as tx_Source_init

try:
    from datetime import timezone
    myutc = timezone.utc
except ImportError:
    # python 2
    from datetime import tzinfo
    ZERO = timedelta(0)
    class UTC(tzinfo):
        """UTC"""
        def utcoffset(self, dt):
            return ZERO
        
        def tzname(self, dt):
            return "UTC"
        
        def dst(self, dt):
            return ZERO

    myutc = UTC()

from roundup.cgi.exceptions import *
from roundup.hyperdb import HyperdbValueError
from roundup.exceptions import *
from roundup import password, hyperdb
from roundup.rest import RestfulInstance, calculate_etag
from roundup.backends import list_backends
from roundup.cgi import client
from roundup.anypy.strings import b2s, s2b, us2u
import random

from roundup.backends.sessions_dbm import OneTimeKeys
from roundup.anypy.dbm_ import anydbm, whichdb

from .db_test_base import setupTracker

from roundup.test.mocknull import MockNull

from io import BytesIO
import json

from copy import copy

try:
    import jwt
    skip_jwt = lambda func, *args, **kwargs: func
except ImportError:
    from .pytest_patcher import mark_class
    jwt=None 
    skip_jwt = mark_class(pytest.mark.skip(
        reason='Skipping JWT tests: jwt library not available'))
    
NEEDS_INSTANCE = 1


class TestCase():

    backend = None
    url_pfx = 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/'

    def setUp(self):
        from packaging import version

        self.dirname = '_test_rest'
        # set up and open a tracker
        # Set optimize=True as code under test (Client.main()::determine_user)
        # will close and re-open the database on user changes. This wipes
        # out additions to the schema needed for testing.
        self.instance = setupTracker(self.dirname, self.backend, optimize=True)

        # open the database
        self.db = self.instance.open('admin')

        # Create the Otk db.
        # This allows a test later on to open the existing db and
        # set a class attribute to test the open retry loop
        # just as though this process was using a pre-existing db
        # rather then the new one we create.
        otk = OneTimeKeys(self.db)
        otk.set('key', key="value")

        # Get user id (user4 maybe). Used later to get data from db.
        self.joeid = self.db.user.create(
            username='joe',
            password=password.Password('random'),
            address='random@home.org',
            realname='Joe Random',
            roles='User'
        )

        self.db.user.set('1', address="admin@admin.com")
        self.db.user.set('2', address="anon@admin.com")
        self.db.commit()
        self.db.close()
        self.db = self.instance.open('joe')
        # Allow joe to retire
        p = self.db.security.addPermission(name='Retire', klass='issue')
        self.db.security.addPermissionToRole('User', p)

        # add set of roles for testing jwt's.
        self.db.security.addRole(name="User:email",
                        description="allow email by jwt")
        # allow the jwt to access everybody's email addresses.
        # this makes it easier to differentiate between User and
        # User:email roles by accessing the /rest/data/user
        # endpoint
        jwt_perms = self.db.security.addPermission(name='View',
                       klass='user',
                       properties=('id', 'realname', 'address', 'username'),
                       description="Allow jwt access to email",
                       props_only=False)
        self.db.security.addPermissionToRole("User:email", jwt_perms)
        self.db.security.addPermissionToRole("User:email", "Rest Access")

        # add set of roles for testing jwt's.
        # this is like the user:email role, but it missing access to the rest endpoint.
        self.db.security.addRole(name="User:emailnorest",
                        description="allow email by jwt")
        jwt_perms = self.db.security.addPermission(name='View',
                       klass='user',
                       properties=('id', 'realname', 'address', 'username'),
                       description="Allow jwt access to email but forget to allow rest",
                       props_only=False)
        self.db.security.addPermissionToRole("User:emailnorest", jwt_perms)


        if jwt:
            # must be 32 chars in length minimum (I think this is at least
            # 256 bits of data)

            secret = "TestingTheJwtSecretTestingTheJwtSecret"
            self.db.config['WEB_JWT_SECRET'] = secret

            # generate all timestamps in UTC.
            base_datetime = datetime(1970,1,1, tzinfo=myutc)

            # A UTC timestamp for now.
            dt = datetime.now(myutc)
            now_ts = int((dt - base_datetime).total_seconds())

            # one good for a minute
            dt = dt + timedelta(seconds=60)
            plus1min_ts = int((dt - base_datetime).total_seconds())

            # one that expired a minute ago
            dt = dt - timedelta(seconds=120)
            expired_ts = int((dt - base_datetime).total_seconds())

            # claims match what cgi/client.py::determine_user
            # is looking for
            claim= { 'sub': self.db.getuid(),
                     'iss': self.db.config.TRACKER_WEB,
                     'aud': self.db.config.TRACKER_WEB,
                     'roles': [ 'User' ],
                     'iat': now_ts,
                     'exp': plus1min_ts,
            }

            # in version 2.0.0 and newer jwt.encode returns string
            # not bytestring. So we have to skip b2s conversion
            
            if version.parse(jwt.__version__) >= version.parse('2.0.0'):
                tostr = lambda x: x
            else:
                tostr = b2s

            self.jwt = {}
            self.claim = {}
            # generate invalid claim with expired timestamp
            self.claim['expired'] = copy(claim)
            self.claim['expired']['exp'] = expired_ts
            self.jwt['expired'] = tostr(jwt.encode(self.claim['expired'], secret,
                                             algorithm='HS256'))
         
            # generate valid claim with user role
            self.claim['user'] = copy(claim)
            self.claim['user']['exp'] = plus1min_ts
            self.jwt['user'] = tostr(jwt.encode(self.claim['user'], secret,
                                          algorithm='HS256'))
            # generate invalid claim bad issuer
            self.claim['badiss'] = copy(claim)
            self.claim['badiss']['iss'] = "http://someissuer/bugs"
            self.jwt['badiss'] = tostr(jwt.encode(self.claim['badiss'], secret,
                                          algorithm='HS256'))
            # generate invalid claim bad aud(ience)
            self.claim['badaud'] = copy(claim)
            self.claim['badaud']['aud'] = "http://someaudience/bugs"
            self.jwt['badaud'] = tostr(jwt.encode(self.claim['badaud'], secret,
                                          algorithm='HS256'))            
            # generate invalid claim bad sub(ject)
            self.claim['badsub'] = copy(claim)
            self.claim['badsub']['sub'] = str("99")
            self.jwt['badsub'] = tostr(jwt.encode(self.claim['badsub'], secret,
                                          algorithm='HS256'))            
            # generate invalid claim bad roles
            self.claim['badroles'] = copy(claim)
            self.claim['badroles']['roles'] = [ "badrole1", "badrole2" ]
            self.jwt['badroles'] = tostr(jwt.encode(self.claim['badroles'], secret,
                                          algorithm='HS256'))            
            # generate valid claim with limited user:email role
            self.claim['user:email'] = copy(claim)
            self.claim['user:email']['roles'] = [ "user:email" ]
            self.jwt['user:email'] = tostr(jwt.encode(self.claim['user:email'], secret,
                                          algorithm='HS256'))

            # generate valid claim with limited user:emailnorest role
            self.claim['user:emailnorest'] = copy(claim)
            self.claim['user:emailnorest']['roles'] = [ "user:emailnorest" ]
            self.jwt['user:emailnorest'] = tostr(jwt.encode(self.claim['user:emailnorest'], secret,
                                          algorithm='HS256'))

        self.db.tx_Source = 'web'

        self.db.issue.addprop(tx_Source=hyperdb.String())
        self.db.issue.addprop(anint=hyperdb.Integer())
        self.db.issue.addprop(afloat=hyperdb.Number())
        self.db.issue.addprop(abool=hyperdb.Boolean())
        self.db.issue.addprop(requireme=hyperdb.String(required=True))
        self.db.user.addprop(issue=hyperdb.Link('issue'))
        self.db.msg.addprop(tx_Source=hyperdb.String())

        self.db.post_init()

        tx_Source_init(self.db)

        env = {
            'PATH_INFO': 'http://localhost/rounduptest/rest/',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest'
        }
        self.dummy_client = client.Client(self.instance, MockNull(), env, [], None)
        self.dummy_client.request.headers.get = self.get_header
        self.empty_form = cgi.FieldStorage()
        self.terse_form = cgi.FieldStorage()
        self.terse_form.list = [
            cgi.MiniFieldStorage('@verbose', '0'),
        ]

        self.server = RestfulInstance(self.dummy_client, self.db)

        self.db.Otk = self.db.getOTKManager()

        self.db.config['WEB_SECRET_KEY'] = "XyzzykrnKm45Sd"

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH):
                raise

    def get_header (self, header, not_found=None):
        try:
            return self.headers[header.lower()]
        except (AttributeError, KeyError, TypeError):
            return not_found

    def create_stati(self):
        try:
            self.db.status.create(name='open', order='9')
        except ValueError:
            pass
        try:
            self.db.status.create(name='closed', order='91')
        except ValueError:
            pass
        try:
            self.db.priority.create(name='normal')
        except ValueError:
            pass
        try:
            self.db.priority.create(name='critical')
        except ValueError:
            pass

    def create_sampledata(self):
        """ Create sample data common to some test cases
        """
        self.create_stati()
        self.db.issue.create(
            title='foo1',
            status=self.db.status.lookup('open'),
            priority=self.db.priority.lookup('normal'),
            nosy = [ "1", "2" ]
        )
        issue_open_norm = self.db.issue.create(
            title='foo2',
            status=self.db.status.lookup('open'),
            priority=self.db.priority.lookup('normal'),
            assignedto = "3"
        )
        issue_open_crit = self.db.issue.create(
            title='foo5',
            status=self.db.status.lookup('open'),
            priority=self.db.priority.lookup('critical')
        )

    def testGet(self):
        """
        Retrieve all three users
        obtain data for 'joe'
        """
        # Retrieve all three users.
        results = self.server.get_collection('user', self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['data']['collection']), 3)
        self.assertEqual(results['data']['@total_size'], 3)
        print(self.dummy_client.additional_headers["X-Count-Total"])
        self.assertEqual(
            self.dummy_client.additional_headers["X-Count-Total"],
            "3"
        )

        # Obtain data for 'joe'.
        results = self.server.get_element('user', self.joeid, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['username'], 'joe')
        self.assertEqual(results['attributes']['realname'], 'Joe Random')

        # Obtain data for 'joe' via username lookup.
        results = self.server.get_element('user', 'joe', self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['username'], 'joe')
        self.assertEqual(results['attributes']['realname'], 'Joe Random')

        # Obtain data for 'joe' via username lookup (long form).
        key = 'username=joe'
        results = self.server.get_element('user', key, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['username'], 'joe')
        self.assertEqual(results['attributes']['realname'], 'Joe Random')

        # Obtain data for 'joe'.
        results = self.server.get_attribute(
            'user', self.joeid, 'username', self.empty_form
        )
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['data'], 'joe')

    def testGetTransitive(self):
        """
        Retrieve all issues with an 'o' in status
        sort by status.name (not order)
        """
        base_path = self.db.config['TRACKER_WEB'] + 'rest/data/'
        #self.maxDiff=None
        self.create_sampledata()
        self.db.issue.set('2', status=self.db.status.lookup('closed'))
        self.db.issue.set('3', status=self.db.status.lookup('chatting'))
        expected={'data':
                   {'@total_size': 2,
                    'collection': [
                      { 'id': '2',
                        'link': base_path + 'issue/2',
                        'assignedto.issue': None,
                        'status':
                          { 'id': '10',
                            'link': base_path + 'status/10'
                          }
                      },
                      { 'id': '1',
                        'link': base_path + 'issue/1',
                        'assignedto.issue': None,
                        'status':
                          { 'id': '9',
                            'link': base_path + 'status/9'
                          }
                      },
                    ]}
                 }
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('status.name', 'o'),
            cgi.MiniFieldStorage('@fields', 'status,assignedto.issue'),
            cgi.MiniFieldStorage('@sort', 'status.name'),
        ]
        results = self.server.get_collection('issue', form)
        self.assertDictEqual(expected, results)

    def testGetExactMatch(self):
        """ Retrieve all issues with an exact title
        """
        base_path = self.db.config['TRACKER_WEB'] + 'rest/data/'
        #self.maxDiff=None
        self.create_sampledata()
        self.db.issue.set('2', title='This is an exact match')
        self.db.issue.set('3', title='This is an exact match')
        self.db.issue.set('1', title='This is AN exact match')
        expected={'data':
                   {'@total_size': 2,
                    'collection': [
                      { 'id': '2',
                        'link': base_path + 'issue/2',
                      },
                      { 'id': '3',
                        'link': base_path + 'issue/3',
                      },
                    ]}
                 }
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('title:', 'This is an exact match'),
            cgi.MiniFieldStorage('@sort', 'status.name'),
        ]
        results = self.server.get_collection('issue', form)
        self.assertDictEqual(expected, results)

    def testOutputFormat(self):
        """ test of @fields and @verbose implementation """

        self.maxDiff = 4000
        self.create_sampledata()
        base_path = self.db.config['TRACKER_WEB'] + 'rest/data/issue/'


        # Check formating for issues status=open; @fields and verbose tests
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('status', 'open'),
            cgi.MiniFieldStorage('@fields', 'nosy,status,creator'),
            cgi.MiniFieldStorage('@verbose', '2')
        ]

        expected={'data':
                   {'@total_size': 3,
                    'collection': [ {
                         'creator': {'id': '3',
                                     'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/3',
                                     'username': 'joe'},
                        'status': {'id': '9',
                                    'name': 'open',
                                    'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/status/9'},
                         'id': '1',
                         'nosy': [
                             {'username': 'admin',
                              'id': '1',
                              'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/1'},
                             {'username': 'anonymous',
                              'id': '2',
                              'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/2'}
                         ],
                         'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/1',
                         'title': 'foo1' },
                        { 'creator': {'id': '3',
                                      'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/3',
                                      'username': 'joe'},
                        'status': {
                            'id': '9',
                            'name': 'open',
                            'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/status/9' },
                         'id': '2',
                         'nosy': [
                             {'username': 'joe',
                              'id': '3',
                              'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/3'}
                         ],
                         'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/2',
                         'title': 'foo2'},
                        {'creator': {'id': '3',
                                     'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/3',
                                     'username': 'joe'},
                            'status': {
                            'id': '9',
                            'name': 'open',
                            'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/status/9'},
                         'id': '3',
                         'nosy': [],
                         'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/3',
                         'title': 'foo5'}
                    ]}}

        results = self.server.get_collection('issue', form)
        self.assertDictEqual(expected, results)

        # Check formating for issues status=open; @fields and verbose tests
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('status', 'open')
            # default cgi.MiniFieldStorage('@verbose', '1')
        ]

        expected={'data':
                   {'@total_size': 3,
                    'collection': [
                        {'id': '1',
                         'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/1',},
                        { 'id': '2',
                         
                         'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/2'},
                        {'id': '3',
                         'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/3'} ]}}
                    

        results = self.server.get_collection('issue', form)
        self.assertDictEqual(expected, results)

        # Generate failure case, unknown field.
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('status', 'open'),
            cgi.MiniFieldStorage('@fields', 'title,foo')
        ]

        expected={'error': {
            'msg': UsageError("Failed to find property 'foo' "
                              "for class issue.",),
            'status': 400}}

        results = self.server.get_collection('issue', form)
        # I tried assertDictEqual but seems it can't handle
        # the exception value of 'msg'. So I am using repr to check.
        self.assertEqual(repr(sorted(expected['error'])),
                         repr(sorted(results['error']))
        )

        # Check formating for issues status=open; @fields and verbose tests
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('status', 'open'),
            cgi.MiniFieldStorage('@fields', 'nosy,status,assignedto'),
            cgi.MiniFieldStorage('@verbose', '0')
        ]

        expected={'data': {
            '@total_size': 3,
            'collection': [
                {'assignedto': None,
                 'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/1',
                 'status': '9',
                 'nosy': ['1', '2'],
                 'id': '1'},
                {'assignedto': '3',
                 'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/2',
                 'status': '9',
                 'nosy': ['3'],
                 'id': '2'},
                {'assignedto': None,
                 'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/3',
                 'status': '9',
                 'nosy': [],
                 'id': '3'}]}}

        results = self.server.get_collection('issue', form)
        print(results)
        self.assertDictEqual(expected, results)

        # check users
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@fields', 'username,queries,password'),
            cgi.MiniFieldStorage('@verbose', '0')
        ]
        # note this is done as user joe, so we only get queries
        # and password for joe.
        expected = {'data': {'collection': [
            {'id': '1',
             'username': 'admin',
             'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/1'},
            {'id': '2',
             'username': 'anonymous',
             'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/2'},
            {'password': '[password hidden scheme PBKDF2]',
             'id': '3',
             'queries': [],
             'username': 'joe',
             'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/3'}],
                '@total_size': 3}}

        results = self.server.get_collection('user', form)
        self.assertDictEqual(expected, results)

        ## Start testing get_element
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@fields', 'queries,password,creator'),
            cgi.MiniFieldStorage('@verbose', '2')
        ]
        expected = {'data': {
            'id': '3',
            'type': 'user',
            '@etag': '',
            'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/3',
            'attributes': {
                'creator': {'id': '1',
                            'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/1',
                            'username': 'admin'},
                'password': '[password hidden scheme PBKDF2]',
                'queries': [],
                'username': 'joe'
            }
        }}

        results = self.server.get_element('user', self.joeid, form)
        results['data']['@etag'] = '' # etag depends on date, set to empty
        self.assertDictEqual(expected,results)

        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@fields', 'status:priority'),
            cgi.MiniFieldStorage('@verbose', '1')
        ]
        expected = {'data': {
            'type': 'issue',
            'id': '3',
            'attributes': {
                'status': {
                    'id': '9', 
                    'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/status/9'},
                'priority': {
                    'id': '1',
                    'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/priority/1'}},
            '@etag': '',
            'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/3'}}

        results = self.server.get_element('issue', "3", form)
        results['data']['@etag'] = '' # etag depends on date, set to empty
        self.assertDictEqual(expected,results)

        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@fields', 'status,priority'),
            cgi.MiniFieldStorage('@verbose', '0')
        ]
        expected = {'data': {
            'type': 'issue',
            'id': '3',
            'attributes': {
                'status': '9', 
                'priority': '1'},
            '@etag': '',
            'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/3'}}

        results = self.server.get_element('issue', "3", form)
        results['data']['@etag'] = '' # etag depends on date, set to empty
        self.assertDictEqual(expected,results)

    def testSorting(self):
        self.maxDiff = 4000
        self.create_sampledata()
        self.db.issue.set('1', status='7')
        self.db.issue.set('2', status='2')
        self.db.issue.set('3', status='2')
        self.db.commit()
        base_path = self.db.config['TRACKER_WEB'] + 'rest/data/issue/'
        # change some data for sorting on later
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@fields', 'status'),
            cgi.MiniFieldStorage('@sort', 'status,-id'),
            cgi.MiniFieldStorage('@verbose', '0')
        ]

        # status is sorted by orderprop (property 'order')
        # which provides the same ordering as the status ID
        expected={'data': {
            '@total_size': 3,
            'collection': [
                {'link': base_path + '3', 'status': '2', 'id': '3'},
                {'link': base_path + '2', 'status': '2', 'id': '2'},
                {'link': base_path + '1', 'status': '7', 'id': '1'}]}}

        results = self.server.get_collection('issue', form)
        self.assertDictEqual(expected, results)

    def testTransitiveField(self):
        """ Test a transitive property in @fields """
        base_path = self.db.config['TRACKER_WEB'] + 'rest/data/'
        # create sample data
        self.create_stati()
        self.db.issue.create(
            title='foo4',
            status=self.db.status.lookup('closed'),
            priority=self.db.priority.lookup('critical')
        )
        # Retrieve all issue @fields=status.name
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@fields', 'status.name')
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)

        exp = [
            {'link': base_path + 'issue/1', 'id': '1', 'status.name': 'closed'}]
        self.assertEqual(results['data']['collection'], exp)

    def testFilter(self):
        """
        Retrieve all three users
        obtain data for 'joe'
        """
        # create sample data
        self.create_stati()
        self.db.issue.create(
            title='foo4',
            status=self.db.status.lookup('closed'),
            priority=self.db.priority.lookup('critical')
        )
        self.db.issue.create(
            title='foo1',
            status=self.db.status.lookup('open'),
            priority=self.db.priority.lookup('normal')
        )
        issue_open_norm = self.db.issue.create(
            title='foo2 normal',
            status=self.db.status.lookup('open'),
            priority=self.db.priority.lookup('normal')
        )
        issue_closed_norm = self.db.issue.create(
            title='foo3 closed normal',
            status=self.db.status.lookup('closed'),
            priority=self.db.priority.lookup('normal')
        )
        issue_closed_crit = self.db.issue.create(
            title='foo4 closed',
            status=self.db.status.lookup('closed'),
            priority=self.db.priority.lookup('critical')
        )
        issue_open_crit = self.db.issue.create(
            title='foo5',
            status=self.db.status.lookup('open'),
            priority=self.db.priority.lookup('critical')
        )
        base_path = self.db.config['TRACKER_WEB'] + 'rest/data/issue/'

        # Retrieve all issue status=open
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('status', 'open')
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertIn(get_obj(base_path, issue_open_norm),
                      results['data']['collection'])
        self.assertIn(get_obj(base_path, issue_open_crit),
                      results['data']['collection'])
        self.assertNotIn(
            get_obj(base_path, issue_closed_norm),
            results['data']['collection']
        )

        # Retrieve all issue status=closed and priority=critical
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('status', 'closed'),
            cgi.MiniFieldStorage('priority', 'critical')
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertIn(get_obj(base_path, issue_closed_crit),
                      results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_crit),
                         results['data']['collection'])
        self.assertNotIn(
            get_obj(base_path, issue_closed_norm),
            results['data']['collection']
        )

        # Retrieve all issue status=closed and priority=normal,critical
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('status', 'closed'),
            cgi.MiniFieldStorage('priority', 'normal,critical')
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertIn(get_obj(base_path, issue_closed_crit),
                      results['data']['collection'])
        self.assertIn(get_obj(base_path, issue_closed_norm),
                      results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_crit),
                         results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_norm),
                         results['data']['collection'])

        # Retrieve all issue status=closed and priority=normal,critical
        # using duplicate priority key's.
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('status', 'closed'),
            cgi.MiniFieldStorage('priority', 'normal'),
            cgi.MiniFieldStorage('priority', 'critical')
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertIn(get_obj(base_path, issue_closed_crit),
                      results['data']['collection'])
        self.assertIn(get_obj(base_path, issue_closed_norm),
                      results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_crit),
                         results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_norm),
                         results['data']['collection'])

        # Retrieve all issues with title containing
        # closed, normal and 3 using duplicate title filterkeys
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('title', 'closed'),
            cgi.MiniFieldStorage('title', 'normal'),
            cgi.MiniFieldStorage('title', '3')
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertNotIn(get_obj(base_path, issue_closed_crit),
                      results['data']['collection'])
        self.assertIn(get_obj(base_path, issue_closed_norm),
                      results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_crit),
                         results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_norm),
                         results['data']['collection'])
        self.assertEqual(len(results['data']['collection']), 1)

        # Retrieve all issues (no hits) with title containing
        # closed, normal and foo3 in this order using title filter
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('title', 'closed normal foo3')
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertNotIn(get_obj(base_path, issue_closed_crit),
                      results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_closed_norm),
                      results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_crit),
                         results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_norm),
                         results['data']['collection'])
        self.assertEqual(len(results['data']['collection']), 0)

        # Retrieve all issues with title containing
        # foo3, closed and normal in this order using title filter
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('title', 'foo3 closed normal')
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertNotIn(get_obj(base_path, issue_closed_crit),
                      results['data']['collection'])
        self.assertIn(get_obj(base_path, issue_closed_norm),
                      results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_crit),
                         results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_norm),
                         results['data']['collection'])
        self.assertEqual(len(results['data']['collection']), 1)

        # Retrieve all issues with word closed in title
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('title', 'closed'),
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertIn(get_obj(base_path, issue_closed_crit),
                      results['data']['collection'])
        self.assertIn(get_obj(base_path, issue_closed_norm),
                      results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_crit),
                         results['data']['collection'])
        self.assertNotIn(get_obj(base_path, issue_open_norm),
                         results['data']['collection'])
        self.assertEqual(len(results['data']['collection']), 2)

    def testPagination(self):
        """
        Test pagination. page_size is required and is an integer
        starting at 1. page_index is optional and is an integer
        starting at 1. Verify that pagination links are present
        if paging, @total_size and X-Count-Total header match
        number of items.        
        """
        # create sample data
        for i in range(0, random.randint(8,15)):
            self.db.issue.create(title='foo' + str(i))

        # Retrieving all the issues
        results = self.server.get_collection('issue', self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        total_length = len(results['data']['collection'])
        # Verify no pagination links if paging not used
        self.assertFalse('@links' in results['data'])
        self.assertEqual(results['data']['@total_size'], total_length)
        self.assertEqual(
            self.dummy_client.additional_headers["X-Count-Total"],
            str(total_length)
        )


        # Pagination will be 45% of the total result
        # So 2 full pages and 1 partial page.
        page_size = total_length * 45 // 100
        page_one_expected = page_size
        page_two_expected = page_size
        page_three_expected = total_length - (2*page_one_expected)
        base_url="http://tracker.example/cgi-bin/roundup.cgi/" \
                 "bugs/rest/data/issue"

        # Retrieve page 1
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@page_size', page_size),
            cgi.MiniFieldStorage('@page_index', 1)
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['data']['collection']),
                         page_one_expected)
        self.assertTrue('@links' in results['data'])
        self.assertTrue('self' in results['data']['@links'])
        self.assertTrue('next' in results['data']['@links'])
        self.assertFalse('prev' in results['data']['@links'])
        self.assertEqual(results['data']['@links']['self'][0]['uri'],
                         "%s?@page_index=1&@page_size=%s"%(base_url,page_size))
        self.assertEqual(results['data']['@links']['next'][0]['uri'],
                         "%s?@page_index=2&@page_size=%s"%(base_url,page_size))

        page_one_results = results # save this for later

        # Retrieve page 2
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@page_size', page_size),
            cgi.MiniFieldStorage('@page_index', 2)
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['data']['collection']), page_two_expected)
        self.assertTrue('@links' in results['data'])
        self.assertTrue('self' in results['data']['@links'])
        self.assertTrue('next' in results['data']['@links'])
        self.assertTrue('prev' in results['data']['@links'])
        self.assertEqual(results['data']['@links']['self'][0]['uri'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue?@page_index=2&@page_size=%s"%page_size)
        self.assertEqual(results['data']['@links']['next'][0]['uri'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue?@page_index=3&@page_size=%s"%page_size)
        self.assertEqual(results['data']['@links']['prev'][0]['uri'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue?@page_index=1&@page_size=%s"%page_size)
        self.assertEqual(results['data']['@links']['self'][0]['rel'],
                         'self')
        self.assertEqual(results['data']['@links']['next'][0]['rel'],
                         'next')
        self.assertEqual(results['data']['@links']['prev'][0]['rel'],
                         'prev')

        # Retrieve page 3
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@page_size', page_size),
            cgi.MiniFieldStorage('@page_index', 3)
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['data']['collection']), page_three_expected)
        self.assertTrue('@links' in results['data'])
        self.assertTrue('self' in results['data']['@links'])
        self.assertFalse('next' in results['data']['@links'])
        self.assertTrue('prev' in results['data']['@links'])
        self.assertEqual(results['data']['@links']['self'][0]['uri'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue?@page_index=3&@page_size=%s"%page_size)
        self.assertEqual(results['data']['@links']['prev'][0]['uri'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue?@page_index=2&@page_size=%s"%page_size)

        # Verify that page_index is optional
        # Should start at page 1
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@page_size', page_size),
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['data']['collection']), page_size)
        self.assertTrue('@links' in results['data'])
        self.assertTrue('self' in results['data']['@links'])
        self.assertTrue('next' in results['data']['@links'])
        self.assertFalse('prev' in results['data']['@links'])
        self.assertEqual(page_one_results, results)

        # FIXME add tests for out of range once we decide what response
        # is needed to:
        #   page_size < 0
        #   page_index < 0

    def testRestRateLimit(self):

        self.db.config['WEB_API_CALLS_PER_INTERVAL'] = 20
        self.db.config['WEB_API_INTERVAL_IN_SEC'] = 60

        # Otk code never passes through the
        # retry loop. Not sure why but I can force it
        # through the loop by setting the internal _db_type
        # setting once the db is created by the previous command.
        try:
            self.db.Otk._db_type = whichdb("%s/%s"%(self.db.Otk.dir, self.db.Otk.name))
        except AttributeError:
            # if dir attribute doesn't exist the primary db is not
            # sqlite or anydbm. So don't need to exercise code.
            pass
        
        print("Now realtime start:", datetime.utcnow())
        # don't set an accept header; json should be the default
        # use up all our allowed api calls
        for i in range(20):
            # i is 0 ... 19
            self.client_error_message = []
            results = self.server.dispatch('GET',
                            "/rest/data/user/%s/realname"%self.joeid,
                            self.empty_form)
 
            # is successful
            self.assertEqual(self.server.client.response_code, 200)
            # does not have Retry-After header as we have
            # suceeded with this query
            self.assertFalse("Retry-After" in
                             self.server.client.additional_headers) 
            # remaining count is correct
            self.assertEqual(
                self.server.client.additional_headers["X-RateLimit-Remaining"],
                str(self.db.config['WEB_API_CALLS_PER_INTERVAL'] -1 - i)
                )

        # trip limit
        self.server.client.additional_headers.clear()
        results = self.server.dispatch('GET',
                     "/rest/data/user/%s/realname"%self.joeid,
                            self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 429)

        self.assertEqual(
            self.server.client.additional_headers["X-RateLimit-Limit"],
            str(self.db.config['WEB_API_CALLS_PER_INTERVAL']))
        self.assertEqual(
            self.server.client.additional_headers["X-RateLimit-Limit-Period"],
            str(self.db.config['WEB_API_INTERVAL_IN_SEC']))
        self.assertEqual(
            self.server.client.additional_headers["X-RateLimit-Remaining"],
            '0')
        # value will be almost 60. Allow 1-2 seconds for all 20 rounds.
        self.assertAlmostEqual(
            float(self.server.client.additional_headers["X-RateLimit-Reset"]),
            59, delta=1)
        self.assertEqual(
            str(self.server.client.additional_headers["Retry-After"]),
            "3")  # check as string

        print("Reset:", self.server.client.additional_headers["X-RateLimit-Reset"])
        print("Now realtime pre-sleep:", datetime.utcnow())
        sleep(3.1) # sleep as requested so we can do another login
        print("Now realtime post-sleep:", datetime.utcnow())

        # this should succeed
        self.server.client.additional_headers.clear()
        results = self.server.dispatch('GET',
                     "/rest/data/user/%s/realname"%self.joeid,
                            self.empty_form)
        print(results)
        print("Reset:", self.server.client.additional_headers["X-RateLimit-Reset-date"])
        print("Now realtime:", datetime.utcnow())
        print("Now ts header:", self.server.client.additional_headers["Now"])
        print("Now date header:", self.server.client.additional_headers["Now-date"])

        self.assertEqual(self.server.client.response_code, 200)

        self.assertEqual(
            self.server.client.additional_headers["X-RateLimit-Limit"],
            str(self.db.config['WEB_API_CALLS_PER_INTERVAL']))
        self.assertEqual(
            self.server.client.additional_headers["X-RateLimit-Limit-Period"],
            str(self.db.config['WEB_API_INTERVAL_IN_SEC']))
        self.assertEqual(
            self.server.client.additional_headers["X-RateLimit-Remaining"],
            '0')
        self.assertFalse("Retry-After" in
                         self.server.client.additional_headers) 
        # we still need to wait a minute for everything to clear
        self.assertAlmostEqual(
            float(self.server.client.additional_headers["X-RateLimit-Reset"]),
            59, delta=1)

        # and make sure we need to wait another three seconds
        # as we consumed the last api call
        results = self.server.dispatch('GET',
                     "/rest/data/user/%s/realname"%self.joeid,
                            self.empty_form)

        self.assertEqual(self.server.client.response_code, 429)
        self.assertEqual(
            str(self.server.client.additional_headers["Retry-After"]),
            "3")  # check as string

        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['error']['msg'],
                         "Api rate limits exceeded. Please wait: 3 seconds.")

        # reset rest params
        self.db.config['WEB_API_CALLS_PER_INTERVAL'] = 0
        self.db.config['WEB_API_INTERVAL_IN_SEC'] = 3600
            
    def testEtagGeneration(self):
        ''' Make sure etag generation is stable
        
            This mocks date.Date() when creating the target to be
            etagged. Differing dates make this test impossible.
        '''
        from roundup import date

        originalDate = date.Date

        dummy=date.Date('2000-06-26.00:34:02.0')

        # is a closure the best way to return a static Date object??
        def dummyDate(adate=None):
            def dummyClosure(adate=None, translator=None):
                return dummy
            return dummyClosure

        date.Date = dummyDate()
        try:
            newuser = self.db.user.create(
                username='john',
                password=password.Password('random1', scheme='plaintext'),
                address='random1@home.org',
                realname='JohnRandom',
                roles='User,Admin'
            )

            # verify etag matches what we calculated in the past
            node = self.db.user.getnode(newuser)
            etag = calculate_etag(node, self.db.config['WEB_SECRET_KEY'])
            items = node.items(protected=True) # include every item
            print(repr(sorted(items)))
            print(etag)
            self.assertEqual(etag, '"07c3a7f214d394cf46220e294a5a53c8"')

            # modify key and verify we have a different etag
            etag = calculate_etag(node, self.db.config['WEB_SECRET_KEY'] + "a")
            items = node.items(protected=True) # include every item
            print(repr(sorted(items)))
            print(etag)
            self.assertNotEqual(etag, '"07c3a7f214d394cf46220e294a5a53c8"')

            # change data and verify we have a different etag
            node.username="Paul"
            etag = calculate_etag(node, self.db.config['WEB_SECRET_KEY'])
            items = node.items(protected=True) # include every item
            print(repr(sorted(items)))
            print(etag)
            self.assertEqual(etag, '"d655801d3a6d51e32891531b06ccecfa"')
        finally:
            date.Date = originalDate
        
    def testEtagProcessing(self):
        '''
        Etags can come from two places:
           If-Match http header
           @etags value posted in the form

        Both will be checked if availble. If either one
        fails, the etag check will fail.

        Run over header only, etag in form only, both,
        each one broke and no etag. Use the put command
        to trigger the etag checking code.
        '''
        for mode in ('header', 'etag', 'both',
                     'brokenheader', 'brokenetag', 'none'):
            try:
                # clean up any old header
                del(self.headers)
            except AttributeError:
                pass

            form = cgi.FieldStorage()
            etag = calculate_etag(self.db.user.getnode(self.joeid),
                                  self.db.config['WEB_SECRET_KEY'])
            form.list = [
                cgi.MiniFieldStorage('data', 'Joe Doe Doe'),
            ]

            if mode == 'header':
                print("Mode = %s"%mode)
                self.headers = {'if-match': etag}
            elif mode == 'etag':
                print("Mode = %s"%mode)
                form.list.append(cgi.MiniFieldStorage('@etag', etag))
            elif mode == 'both':
                print("Mode = %s"%mode)
                self.headers = {'etag': etag}
                form.list.append(cgi.MiniFieldStorage('@etag', etag))
            elif mode == 'brokenheader':
                print("Mode = %s"%mode)
                self.headers = {'if-match': 'bad'}
                form.list.append(cgi.MiniFieldStorage('@etag', etag))
            elif mode == 'brokenetag':
                print("Mode = %s"%mode)
                self.headers = {'if-match': etag}
                form.list.append(cgi.MiniFieldStorage('@etag', 'bad'))
            elif mode == 'none':
                print( "Mode = %s"%mode)
            else:
                self.fail("unknown mode found")

            results = self.server.put_attribute(
                'user', self.joeid, 'realname', form
            )
            if mode not in ('brokenheader', 'brokenetag', 'none'):
                self.assertEqual(self.dummy_client.response_code, 200)
            else:
                self.assertEqual(self.dummy_client.response_code, 412)

    def testBinaryFieldStorage(self):
        ''' attempt to exercise all paths in the BinaryFieldStorage
            class
        '''

        expected={ "data": {
                      "link": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/1", 
                      "id": "1"
                   }
                }

        body=b'{ "title": "Joe Doe has problems", \
                 "nosy": [ "1", "3" ], \
                 "assignedto": "2", \
                 "abool": true, \
                 "afloat": 2.3, \
                 "anint": 567890 \
        }'
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }
        headers={"accept": "application/json; version=1",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": env['CONTENT_LENGTH'],
        }
        self.headers=headers
        # we need to generate a FieldStorage the looks like
        #  FieldStorage(None, None, 'string') rather than
        #  FieldStorage(None, None, [])
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch(env["REQUEST_METHOD"],
                            "/rest/data/issue",
                            form)
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict,expected)

    def testDispatchPost(self):
        """
        run POST through rest dispatch(). This also tests
        sending json payload through code as dispatch is the
        code that changes json payload into something we can
        process.
        """

        # TEST #0
        # POST: issue make joe assignee and admin and demo as
        # nosy
        # simulate: /rest/data/issue
        body=b'{ "title": "Joe Doe has problems", \
                 "nosy": [ "1", "3" ], \
                 "assignedto": "2", \
                 "abool": true, \
                 "afloat": 2.3, \
                 "anint": 567890 \
        }'
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }
        headers={"accept": "application/json; version=1",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": env['CONTENT_LENGTH'],
        }
        self.headers=headers
        # we need to generate a FieldStorage the looks like
        #  FieldStorage(None, None, 'string') rather than
        #  FieldStorage(None, None, [])
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch(env["REQUEST_METHOD"],
                            "/rest/data/issue",
                            form)

        print(results)
        self.assertEqual(self.server.client.response_code, 201)
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['data']['link'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/1")
        self.assertEqual(json_dict['data']['id'], "1")
        results = self.server.dispatch('GET',
                            "/rest/data/issue/1", self.empty_form)
        print(results)
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['data']['link'],
          "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue/1")
        self.assertEqual(json_dict['data']['attributes']['abool'], True)
        self.assertEqual(json_dict['data']['attributes']['afloat'], 2.3)
        self.assertEqual(json_dict['data']['attributes']['anint'], 567890)
        self.assertEqual(len(json_dict['data']['attributes']['nosy']), 3)
        self.assertEqual(json_dict['data']['attributes']\
                          ['assignedto']['link'],
           "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/2")


    def testDispatchDelete(self):
        """
        run Delete through rest dispatch().
        """

        # TEST #0
        # Delete class raises unauthorized error
        # simulate: /rest/data/issue
        env = { "REQUEST_METHOD": "DELETE"
        }
        headers={"accept": "application/json; version=1",
        }
        self.headers=headers
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch(env["REQUEST_METHOD"],
                            "/rest/data/issue",
                            self.empty_form)

        print(results)
        self.assertEqual(self.server.client.response_code, 403)
        json_dict = json.loads(b2s(results))

        self.assertEqual(json_dict['error']['msg'],
                         "Deletion of a whole class disabled")


    def testDispatchBadContent(self):
        """
        runthrough rest dispatch() with bad content_type patterns.
        """

        # simulate: /rest/data/issue
        body=b'{ "title": "Joe Doe has problems", \
                 "nosy": [ "1", "3" ], \
                 "assignedto": "2", \
                 "abool": true, \
                 "afloat": 2.3, \
                 "anint": 567890 \
        }'
        env = { "CONTENT_TYPE": "application/jzot",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }

        headers={"accept": "application/json; version=1",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": env['CONTENT_LENGTH'],
        }

        self.headers=headers
        # we need to generate a FieldStorage the looks like
        #  FieldStorage(None, None, 'string') rather than
        #  FieldStorage(None, None, [])
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch(env["REQUEST_METHOD"],
                            "/rest/data/issue",
                            form)

        print(results)
        self.assertEqual(self.server.client.response_code, 415)
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['error']['msg'],
                         "Unable to process input of type application/jzot")

        # Test GET as well. I am not sure if this should pass or not.
        # Arguably GET doesn't use any form/json input but....
        results = self.server.dispatch('GET',
                            "/rest/data/issue",
                            form)
        print(results)
        self.assertEqual(self.server.client.response_code, 415)



    def testDispatchBadAccept(self):
        # simulate: /rest/data/issue expect failure unknown accept settings
        body=b'{ "title": "Joe Doe has problems", \
                 "nosy": [ "1", "3" ], \
                 "assignedto": "2", \
                 "abool": true, \
                 "afloat": 2.3, \
                 "anint": 567890 \
        }'
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }

        headers={"accept": "application/zot; version=1; q=0.5",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": env['CONTENT_LENGTH'],
        }

        self.headers=headers
        # we need to generate a FieldStorage the looks like
        #  FieldStorage(None, None, 'string') rather than
        #  FieldStorage(None, None, [])
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch(env["REQUEST_METHOD"],
                            "/rest/data/issue",
                            form)

        print(results)
        self.assertEqual(self.server.client.response_code, 406)
        self.assertIn(b"Requested content type 'application/zot; version=1; q=0.5' is not available.\nAcceptable types: */*, application/json", results)

        # simulate: /rest/data/issue works, multiple acceptable output, one
        # is valid
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }

        headers={"accept": "application/zot; version=1; q=0.75, "
                           "application/json; version=1; q=0.5",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": env['CONTENT_LENGTH'],
        }

        self.headers=headers
        # we need to generate a FieldStorage the looks like
        #  FieldStorage(None, None, 'string') rather than
        #  FieldStorage(None, None, [])
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch(env["REQUEST_METHOD"],
                            "/rest/data/issue",
                            form)

        print(results)
        self.assertEqual(self.server.client.response_code, 201)
        json_dict = json.loads(b2s(results))
        # ERROR this should be 1. What's happening is that the code
        # for handling 406 error code runs through everything and creates
        # the item. Then it throws a 406 after the work is done when it
        # realizes it can't respond as requested. So the 406 post above
        # creates issue 1 and this one creates issue 2.
        self.assertEqual(json_dict['data']['id'], "2")


        # test 3 accept is empty. This triggers */* so passes
        headers={"accept": "",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": env['CONTENT_LENGTH'],
        }

        self.headers=headers
        # we need to generate a FieldStorage the looks like
        #  FieldStorage(None, None, 'string') rather than
        #  FieldStorage(None, None, [])
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch(env["REQUEST_METHOD"],
                            "/rest/data/issue",
                            form)

        print(results)
        self.assertEqual(self.server.client.response_code, 201)
        json_dict = json.loads(b2s(results))
        # This is one more than above. Will need to be fixed
        # When error above is fixed.
        self.assertEqual(json_dict['data']['id'], "3")

        # test 4 accept is random junk.
        headers={"accept": "Xyzzy I am not a mime, type;",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": env['CONTENT_LENGTH'],
        }

        self.headers=headers
        # we need to generate a FieldStorage the looks like
        #  FieldStorage(None, None, 'string') rather than
        #  FieldStorage(None, None, [])
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch(env["REQUEST_METHOD"],
                            "/rest/data/issue",
                            form)

        print(results)
        self.assertEqual(self.server.client.response_code, 406)
        json_dict = json.loads(b2s(results))
        self.assertIn('Unable to parse Accept Header. Invalid media type: Xyzzy I am not a mime. Acceptable types: */* application/json', json_dict['error']['msg'])

        # test 5 accept mimetype is ok, param is not
        headers={"accept": "*/*; foo",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": env['CONTENT_LENGTH'],
        }

        self.headers=headers
        # we need to generate a FieldStorage the looks like
        #  FieldStorage(None, None, 'string') rather than
        #  FieldStorage(None, None, [])
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch(env["REQUEST_METHOD"],
                            "/rest/data/issue",
                            form)

        print(results)
        self.assertEqual(self.server.client.response_code, 406)
        json_dict = json.loads(b2s(results))
        self.assertIn('Unable to parse Accept Header. Invalid param: foo. Acceptable types: */* application/json', json_dict['error']['msg'])

    def testStatsGen(self):
        # check stats being returned by put and get ops
        # using dispatch which parses the @stats query param

        # find correct py2/py3 list comparison ignoring order
        try:
            list_test = self.assertCountEqual  # py3
        except AttributeError:
            list_test = self.assertItemsEqual  # py2.7+

        # get stats
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@stats', 'True'),
        ]
        results = self.server.dispatch('GET',
                 "/rest/data/user/1/realname",
                                 form)
        self.assertEqual(self.dummy_client.response_code, 200)
        json_dict = json.loads(b2s(results))

        # check that @stats are defined
        self.assertTrue( '@stats' in json_dict['data'] )
        # check that the keys are present
        # not validating values as that changes
        valid_fields= [ us2u('elapsed'),
                        us2u('cache_hits'),
                        us2u('cache_misses'),
                        us2u('get_items'),
                        us2u('filtering') ]
        list_test(valid_fields,json_dict['data']['@stats'].keys())

        # Make sure false value works to suppress @stats
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@stats', 'False'),
        ]
        results = self.server.dispatch('GET',
                 "/rest/data/user/1/realname",
                                 form)
        self.assertEqual(self.dummy_client.response_code, 200)
        json_dict = json.loads(b2s(results))
        print(results)
        # check that @stats are not defined
        self.assertTrue( '@stats' not in json_dict['data'] )

        # Make sure non-true value works to suppress @stats
        # false will always work
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@stats', 'random'),
        ]
        results = self.server.dispatch('GET',
                 "/rest/data/user/1/realname",
                                 form)
        self.assertEqual(self.dummy_client.response_code, 200)
        json_dict = json.loads(b2s(results))
        print(results)
        # check that @stats are not defined
        self.assertTrue( '@stats' not in json_dict['data'] )

        # if @stats is not defined there should be no stats
        results = self.server.dispatch('GET',
                 "/rest/data/user/1/realname",
                                 self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        json_dict = json.loads(b2s(results))

        # check that @stats are not defined
        self.assertTrue( '@stats' not in json_dict['data'] )



        # change admin's realname via a normal web form
        # This generates a FieldStorage that looks like:
        #  FieldStorage(None, None, [])
        # use etag from header
        #
        # Also use GET on the uri via the dispatch to retrieve
        # the results from the db.
        etag = calculate_etag(self.db.user.getnode('1'),
                              self.db.config['WEB_SECRET_KEY'])
        headers={"if-match": etag,
                 "accept": "application/vnd.json.test-v1+json",
        }
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('data', 'Joe Doe'),
            cgi.MiniFieldStorage('@apiver', '1'),
            cgi.MiniFieldStorage('@stats', 'true'),
        ]
        self.headers = headers
        self.server.client.request.headers.get = self.get_header
        self.db.setCurrentUser('admin') # must be admin to change user
        results = self.server.dispatch('PUT',
                            "/rest/data/user/1/realname",
                            form)
        self.assertEqual(self.dummy_client.response_code, 200)
        json_dict = json.loads(b2s(results))
        list_test(valid_fields,json_dict['data']['@stats'].keys())

    def testDispatch(self):
        """
        run changes through rest dispatch(). This also tests
        sending json payload through code as dispatch is the
        code that changes json payload into something we can
        process.
        """
        # TEST #1
        # PUT: joe's 'realname' using json data.
        # simulate: /rest/data/user/<id>/realname
        # use etag in header
        etag = calculate_etag(self.db.user.getnode(self.joeid),
                              self.db.config['WEB_SECRET_KEY'])
        body=b'{ "data": "Joe Doe 1" }'
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "PUT"
        }
        headers={"accept": "application/json; version=1",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": env['CONTENT_LENGTH'],
                 "if-match": etag
        }
        self.headers=headers
        # we need to generate a FieldStorage the looks like
        #  FieldStorage(None, None, 'string') rather than
        #  FieldStorage(None, None, [])
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('PUT',
                            "/rest/data/user/%s/realname"%self.joeid,
                            form)

        self.assertEqual(self.server.client.response_code, 200)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['realname'],
                         'Joe Doe 1')


        # substitute the version with an unacceptable version
        # and verify it returns 400 code.
        self.headers["accept"] = "application/json; version=1.1"
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('PUT',
                            "/rest/data/user/%s/realname"%self.joeid,
                            form)
        self.assertEqual(self.server.client.response_code, 400)
        del(self.headers)

        # TEST #2
        # Set joe's 'realname' using json data.
        # simulate: /rest/data/user/<id>/realname
        # use etag in payload
        etag = calculate_etag(self.db.user.getnode(self.joeid),
                              self.db.config['WEB_SECRET_KEY'])
        etagb = etag.strip ('"')
        body=s2b('{ "@etag": "\\"%s\\"", "data": "Joe Doe 2" }'%etagb)
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "PUT",
        }
        self.headers=None  # have FieldStorage get len from env.
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=None,
                                environ=env)
        self.server.client.request.headers.get=self.get_header

        headers={"accept": "application/json",
                 "content-type": env['CONTENT_TYPE'],
                 "if-match": etag
        }
        self.headers=headers # set for dispatch

        results = self.server.dispatch('PUT',
                            "/rest/data/user/%s/realname"%self.joeid,
                            form)

        self.assertEqual(self.server.client.response_code, 200)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['realname'],
                         'Joe Doe 2')
        del(self.headers)

        # TEST #3
        # change Joe's realname via a normal web form
        # This generates a FieldStorage that looks like:
        #  FieldStorage(None, None, [])
        # use etag from header
        #
        # Also use GET on the uri via the dispatch to retrieve
        # the results from the db.
        etag = calculate_etag(self.db.user.getnode(self.joeid),
                              self.db.config['WEB_SECRET_KEY'])
        headers={"if-match": etag,
                 "accept": "application/vnd.json.test-v1+json",
        }
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('data', 'Joe Doe'),
            cgi.MiniFieldStorage('@apiver', '1'),
        ]
        self.headers = headers
        self.server.client.request.headers.get = self.get_header
        results = self.server.dispatch('PUT',
                            "/rest/data/user/%s/realname"%self.joeid,
                            form)
        self.assertEqual(self.dummy_client.response_code, 200)
        results = self.server.dispatch('GET',
                            "/rest/data/user/%s/realname"%self.joeid,
                                       self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        json_dict = json.loads(b2s(results))

        self.assertEqual(json_dict['data']['data'], 'Joe Doe')
        self.assertEqual(json_dict['data']['link'],
                         "http://tracker.example/cgi-bin/"
                         "roundup.cgi/bugs/rest/data/user/3/realname") 
        self.assertIn(json_dict['data']['type'], ("<class 'str'>",
                                                  "<type 'str'>"))
        self.assertEqual(json_dict['data']["id"], "3")
        del(self.headers)


        # TEST #4
        # PATCH: joe's email address with json
        # save address so we can use it later
        stored_results = self.server.get_element('user', self.joeid,
                                                 self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)

        etag = calculate_etag(self.db.user.getnode(self.joeid),
                              self.db.config['WEB_SECRET_KEY'])
        etagb = etag.strip ('"')
        body=s2b('{ "address": "demo2@example.com", "@etag": "\\"%s\\""}'%etagb)
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "PATCH"
        }
        headers={"accept": "application/json",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": len(body)
        }
        self.headers=headers
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('PATCH',
                            "/rest/data/user/%s"%self.joeid,
                            form)

        self.assertEqual(self.server.client.response_code, 200)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['address'],
                         'demo2@example.com')

        # and set it back reusing env and headers from last test
        etag = calculate_etag(self.db.user.getnode(self.joeid),
                              self.db.config['WEB_SECRET_KEY'])
        etagb = etag.strip ('"')
        body=s2b('{ "address": "%s", "@etag": "\\"%s\\""}'%(
            stored_results['data']['attributes']['address'],
            etagb))
        # reuse env and headers from prior test.
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('PATCH',
                            "/rest/data/user/%s"%self.joeid,
                            form)

        self.assertEqual(self.server.client.response_code, 200)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['address'],
                         'random@home.org')
        del(self.headers)

        # TEST #5
        # POST: create new issue
        # no etag needed
        etag = "not needed"
        body=b'{ "title": "foo bar", "priority": "critical" }'
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }
        headers={"accept": "application/json",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": len(body)
        }
        self.headers=headers
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            "/rest/data/issue",
                            form)

        self.assertEqual(self.server.client.response_code, 201)
        json_dict = json.loads(b2s(results))
        issue_id=json_dict['data']['id']
        results = self.server.get_element('issue',
                            str(issue_id), # must be a string not unicode
                            self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['title'],
                         'foo bar')

        # TEST #6
        # POST: an invalid class
        # no etag needed
        etag = "not needed"
        body=b'{ "title": "foo bar", "priority": "critical" }'
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }
        headers={"accept": "application/json",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": len(body)
        }
        self.headers=headers
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            "/rest/data/nonissue",
                            form)

        self.assertEqual(self.server.client.response_code, 404)
        json_dict = json.loads(b2s(results))
        status=json_dict['error']['status']
        msg=json_dict['error']['msg']
        self.assertEqual(status, 404)
        self.assertEqual(msg, 'Class nonissue not found')

        # TEST #7
        # POST: status without key field of name
        # also test that version spec in accept header is accepted
        # no etag needed
        etag = "not needed"
        body=b'{ "order": 5 }'
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }
        headers={"accept": "application/json; version=1",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": len(body)
        }
        self.headers=headers
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        self.db.setCurrentUser('admin') # must be admin to create status
        results = self.server.dispatch('POST',
                            "/rest/data/status",
                            form)

        self.assertEqual(self.server.client.response_code, 400)
        json_dict = json.loads(b2s(results))
        status=json_dict['error']['status']
        msg=json_dict['error']['msg']
        self.assertEqual(status, 400)
        self.assertEqual(msg, "Must provide the 'name' property.")


        # TEST #8
        # DELETE: delete issue 1 also test return type by extension
        #         test bogus extension as well.
        etag = calculate_etag(self.db.issue.getnode("1"),
                              self.db.config['WEB_SECRET_KEY'])
        etagb = etag.strip ('"')
        env = {"CONTENT_TYPE": "application/json",
               "CONTENT_LEN": 0,
               "REQUEST_METHOD": "DELETE" }
        # use text/plain header and request json output by appending
        # .json to the url.
        headers={"accept": "text/plain",
                 "content-type": env['CONTENT_TYPE'],
                 "if-match": '"%s"'%etagb,
                 "content-length": 0,
        }
        self.headers=headers
        body_file=BytesIO(b'')  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        self.db.setCurrentUser('admin') # must be admin to delete issue
        results = self.server.dispatch('DELETE',
                            "/rest/data/issue/1.json",
                            form)
        self.assertEqual(self.server.client.response_code, 200)
        print(results)
        json_dict = json.loads(b2s(results))
        status=json_dict['data']['status']
        self.assertEqual(status, 'ok')

        results = self.server.dispatch('GET',
                            "/rest/data/issuetitle:=asdf.jon",
                            form)
        self.assertEqual(self.server.client.response_code, 406)
        print(results)
        try:  # only verify local copy not system installed copy
            from roundup.dicttoxml import dicttoxml
            includexml = ', application/xml'
        except ImportError:
            includexml = ''
        
        response="Requested content type 'jon' is not available.\n" \
                 "Acceptable types: */*, application/json%s\n"%includexml
        self.assertEqual(b2s(results), response)

        # TEST #9
        # GET: test that version can be set with accept:
        #    ... ; version=z
        # or
        #    application/vnd.x.y-vz+json
        # or
        #    @apiver
        # simulate: /rest/data/issue
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@apiver', 'L'),
        ]
        headers={"accept": "application/json; notversion=z" }
        self.headers=headers
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('GET',
                            "/rest/data/issue/1", form)
        print("9a: " + b2s(results))
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['error']['status'], 400)
        self.assertEqual(json_dict['error']['msg'],
              "Unrecognized version: L. See /rest without "
              "specifying version for supported versions.")

        headers={"accept": "application/json; version=z" }
        self.headers=headers
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('GET',
                            "/rest/data/issue/1", form)
        print("9b: " + b2s(results))
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['error']['status'], 400)
        self.assertEqual(json_dict['error']['msg'],
              "Unrecognized version: z. See /rest without "
              "specifying version for supported versions.")

        headers={"accept": "application/vnd.roundup.test-vz+json" }
        self.headers=headers
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('GET',
                            "/rest/data/issue/1", self.empty_form)
        print("9c:" + b2s(results))
        self.assertEqual(self.server.client.response_code, 400)
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['error']['status'], 400)
        self.assertEqual(json_dict['error']['msg'],
              "Unrecognized version: z. See /rest without "
              "specifying version for supported versions.")

        # verify that version priority is correct; should be version=...
        headers={"accept": "application/vnd.roundup.test-vz+json; version=a"
        }
        self.headers=headers
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('GET',
                            "/rest/data/issue/1", self.empty_form)
        print("9d: " + b2s(results))
        self.assertEqual(self.server.client.response_code, 400)
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['error']['status'], 400)
        self.assertEqual(json_dict['error']['msg'],
              "Unrecognized version: a. See /rest without "
              "specifying version for supported versions.")

        # TEST #10
        # check /rest and /rest/summary and /rest/notthere
        expected_rest = {
          "data": {
              "supported_versions": [
                  1
              ],
              "default_version": 1,
              "links": [
                  {
                      "rel": "summary",
                      "uri": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/summary"
                  },
                  {
                      "rel": "self",
                      "uri": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest"
                  },
                  {
                      "rel": "data",
                      "uri": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data"
                  }
              ]
          }
        }

        self.headers={}
        results = self.server.dispatch('GET',
                            "/rest", self.empty_form)
        print("10a: " + b2s(results))
        self.assertEqual(self.server.client.response_code, 200)
        results_dict = json.loads(b2s(results))
        self.assertEqual(results_dict, expected_rest)


        results = self.server.dispatch('GET',
                            "/rest/", self.empty_form)
        print("10b: " + b2s(results))
        self.assertEqual(self.server.client.response_code, 200)
        results_dict = json.loads(b2s(results))
        self.assertEqual(results_dict, expected_rest)

        results = self.server.dispatch('GET',
                            "/rest/summary", self.empty_form)
        print("10c: " + b2s(results))
        self.assertEqual(self.server.client.response_code, 200)

        results = self.server.dispatch('GET',
                            "/rest/summary/", self.empty_form)
        print("10d: " + b2s(results))
        self.assertEqual(self.server.client.response_code, 200)

        expected_data = {
            "data": {
                "issue": {
                    "link": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue"
                },
                "priority": {
                    "link": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/priority"
                },
                "user": {
                    "link": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user"
                },
                "query": {
                    "link": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/query"
                },
                "status": {
                    "link": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/status"
                },
                "keyword": {
                    "link": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/keyword"
                },
                "msg": {
                    "link": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/msg"
                },
                "file": {
                    "link": "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/file"
                }
            }
        }

        results = self.server.dispatch('GET',
                            "/rest/data", self.empty_form)
        print("10e: " + b2s(results))
        self.assertEqual(self.server.client.response_code, 200)
        results_dict = json.loads(b2s(results))
        self.assertEqual(results_dict, expected_data)

        results = self.server.dispatch('GET',
                            "/rest/data/", self.empty_form)
        print("10f: " + b2s(results))
        self.assertEqual(self.server.client.response_code, 200)
        results_dict = json.loads(b2s(results))
        self.assertEqual(results_dict, expected_data)

        results = self.server.dispatch('GET',
                            "/rest/notthere", self.empty_form)
        self.assertEqual(self.server.client.response_code, 404)

        results = self.server.dispatch('GET',
                            "/rest/notthere/", self.empty_form)
        self.assertEqual(self.server.client.response_code, 404)

        del(self.headers)

    def testAcceptHeaderParsing(self):
        # TEST #1
        # json highest priority
        self.server.client.request.headers.get=self.get_header
        headers={"accept": "application/json; version=1,"
                           "application/xml; q=0.5; version=2,"
                           "text/plain; q=0.75; version=2"
        }
        self.headers=headers
        results = self.server.dispatch('GET',
                                       "/rest/data/status/1",
                                       self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        self.assertEqual(self.server.client.additional_headers['Content-Type'],
                         "application/json")

        # TEST #2
        # text highest priority
        headers={"accept": "application/json; q=0.5; version=1,"
                           "application/xml; q=0.25; version=2,"
                           "text/plain; q=1.0; version=3"
        }
        self.headers=headers
        results = self.server.dispatch('GET',
                                       "/rest/data/status/1",
                                       self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        self.assertEqual(self.server.client.additional_headers['Content-Type'],
                         "application/json")

        # TEST #3
        # no acceptable type
        headers={"accept": "text/plain; q=1.0; version=2"
        }
        self.headers=headers
        results = self.server.dispatch('GET',
                                       "/rest/data/status/1",
                                       self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 406)
        self.assertEqual(self.server.client.additional_headers['Content-Type'],
                         "application/json")

        # TEST #4
        # no accept header, should use default json
        headers={}
        self.headers=headers
        results = self.server.dispatch('GET',
                                       "/rest/data/status/1",
                                       self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        self.assertEqual(self.server.client.additional_headers['Content-Type'],
                         "application/json")

        # TEST #5
        # wildcard accept header, should use default json
        headers={ "accept": "*/*"}
        self.headers=headers
        results = self.server.dispatch('GET',
                                       "/rest/data/status/1",
                                       self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        self.assertEqual(self.server.client.additional_headers['Content-Type'],
                         "application/json")

        # TEST #6
        # invalid q factor if not ignored/demoted
        # application/json is selected with invalid version
        # and errors.
        # this ends up choosing */* which triggers json.
        self.server.client.request.headers.get=self.get_header
        headers={"accept": "application/json; q=1.5; version=99,"
                           "*/*; q=0.9; version=1,"
                           "text/plain; q=3.75; version=2"
        }
        self.headers=headers
        results = self.server.dispatch('GET',
                                       "/rest/data/status/1",
                                       self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        self.assertEqual(self.server.client.additional_headers['Content-Type'],
                         "application/json")


        '''
        # only works if dicttoxml.py is installed.
        #   not installed for testing
        # TEST #7
        # xml wins
        headers={"accept": "application/json; q=0.5; version=2,"
                           "application/xml; q=0.75; version=1,"
                           "text/plain; q=1.0; version=2"
        }
        self.headers=headers
        results = self.server.dispatch('GET',
                                       "/rest/data/status/1",
                                       self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        self.assertEqual(self.server.client.additional_headers['Content-Type'],
                         "application/xml")
        '''

        # TEST #8
        # invalid api version
        # application/json is selected with invalid version
        self.server.client.request.headers.get=self.get_header
        headers={"accept": "application/json; version=99"
        }
        self.headers=headers
        with self.assertRaises(UsageError) as ctx:
            results = self.server.dispatch('GET',
                                           "/rest/data/status/1",
                                           self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        self.assertEqual(ctx.exception.args[0],
                         "Unrecognized version: 99. See /rest without "
                         "specifying version for supported versions.")

    def testMethodOverride(self):
        # TEST #1
        # Use GET, PUT, PATCH to tunnel DELETE expect error
        
        body=b'{ "order": 5 }'
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }
        body_file=BytesIO(body)  # FieldStorage needs a file
        self.server.client.request.headers.get=self.get_header
        for method in ( "GET", "PUT", "PATCH" ):
            headers={"accept": "application/json; version=1",
                     "content-type": env['CONTENT_TYPE'],
                     "content-length": len(body),
                     "x-http-method-override": "DElETE",
                 }
            self.headers=headers
            form = client.BinaryFieldStorage(body_file,
                                         headers=headers,
                                         environ=env)
            self.db.setCurrentUser('admin') # must be admin to create status
            results = self.server.dispatch(method,
                                           "/rest/data/status",
                                           form)

            self.assertEqual(self.server.client.response_code, 400)
            json_dict = json.loads(b2s(results))
            status=json_dict['error']['status']
            msg=json_dict['error']['msg']
            self.assertEqual(status, 400)
            self.assertEqual(msg, "X-HTTP-Method-Override: DElETE must be "
                             "used with POST method not %s."%method)

        # TEST #2
        # DELETE: delete issue 1 via post tunnel
        self.assertFalse(self.db.status.is_retired("1"))
        etag = calculate_etag(self.db.status.getnode("1"),
                              self.db.config['WEB_SECRET_KEY'])
        etagb = etag.strip ('"')
        headers={"accept": "application/json; q=1.0, application/xml; q=0.75",
                 "if-match": '"%s"'%etagb,
                 "content-length": 0,
                 "x-http-method-override": "DElETE"
        }
        self.headers=headers
        body_file=BytesIO(b'')  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        self.db.setCurrentUser('admin') # must be admin to delete issue
        results = self.server.dispatch('POST',
                            "/rest/data/status/1",
                            form)
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        json_dict = json.loads(b2s(results))
        status=json_dict['data']['status']
        self.assertEqual(status, 'ok')
        self.assertTrue(self.db.status.is_retired("1"))
        

    def testPostPOE(self):
        ''' test post once exactly: get POE url, create issue
            using POE url. Use dispatch entry point.
        '''
        import time
        # setup environment
        etag = "not needed"
        empty_body=b''
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(empty_body),
                "REQUEST_METHOD": "POST"
        }
        headers={"accept": "application/json",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": len(empty_body)
        }
        self.headers=headers
        # use empty_body to test code path for missing/empty json
        body_file=BytesIO(empty_body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)

        ## Obtain the POE url.
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            "/rest/data/issue/@poe",
                            form)

        self.assertEqual(self.server.client.response_code, 200)
        json_dict = json.loads(b2s(results))
        url=json_dict['data']['link']

        # strip tracker web prefix leaving leading /.
        url = url[len(self.db.config['TRACKER_WEB'])-1:]

        ## create an issue using poe url.
        body=b'{ "title": "foo bar", "priority": "critical" }'
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }
        headers={"accept": "application/json",
                 "content-type": env['CONTENT_TYPE'],
                 "content-length": len(body)
        }
        self.headers=headers
        body_file=BytesIO(body)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            url,
                            form)

        self.assertEqual(self.server.client.response_code, 201)
        json_dict = json.loads(b2s(results))
        issue_id=json_dict['data']['id']
        results = self.server.get_element('issue',
                            str(issue_id), # must be a string not unicode
                            self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['title'],
                         'foo bar')

        ## Reuse POE url. It will fail.
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            url,
                            form)
        # get the last component stripping the trailing /
        poe=url[url.rindex('/')+1:]
        self.assertEqual(self.server.client.response_code, 400)
        results = json.loads(b2s(results))
        self.assertEqual(results['error']['status'], 400)
        self.assertEqual(results['error']['msg'],
                         "POE token \'%s\' not valid."%poe)

        ## Try using GET on POE url. Should fail with method not
        ## allowed (405)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('GET',
                            "/rest/data/issue/@poe",
                            form)
        self.assertEqual(self.server.client.response_code, 405)


        ## Try creating generic POE url.
        body_poe=b'{"generic": "null", "lifetime": "100" }'
        body_file=BytesIO(body_poe)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            "/rest/data/issue/@poe",
                            form)
        json_dict = json.loads(b2s(results))
        url=json_dict['data']['link']

        # strip tracker web prefix leaving leading /.
        url = url[len(self.db.config['TRACKER_WEB'])-1:]
        url = url.replace('/issue/', '/keyword/')

        body_keyword=b'{"name": "keyword"}'
        body_file=BytesIO(body_keyword)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        results = self.server.dispatch('POST',
                            url,
                            form)
        self.assertEqual(self.server.client.response_code, 201)
        json_dict = json.loads(b2s(results))
        url=json_dict['data']['link']
        id=json_dict['data']['id']
        self.assertEqual(id, "1")
        self.assertEqual(url, "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/keyword/1")

        ## Create issue POE url and try to use for keyword.
        ## This should fail.
        body_poe=b'{"lifetime": "100" }'
        body_file=BytesIO(body_poe)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            "/rest/data/issue/@poe",
                            form)
        json_dict = json.loads(b2s(results))
        url=json_dict['data']['link']

        # strip tracker web prefix leaving leading /.
        url = url[len(self.db.config['TRACKER_WEB'])-1:]
        url = url.replace('/issue/', '/keyword/')

        body_keyword=b'{"name": "keyword"}'
        body_file=BytesIO(body_keyword)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        results = self.server.dispatch('POST',
                            url,
                            form)
        poe=url[url.rindex('/')+1:]
        self.assertEqual(self.server.client.response_code, 400)
        json_dict = json.loads(b2s(results))
        stat=json_dict['error']['status']
        msg=json_dict['error']['msg']
        self.assertEqual(stat, 400)
        self.assertEqual(msg, "POE token '%s' not valid for keyword, was generated for class issue"%poe)


        ## Create POE with 10 minute lifetime and verify
        ## expires is within 10 minutes.
        body_poe=b'{"lifetime": "30" }'
        body_file=BytesIO(body_poe)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            "/rest/data/issue/@poe",
                            form)
        json_dict = json.loads(b2s(results))
        expires=int(json_dict['data']['expires'])
        # allow up to 3 seconds between time stamp creation
        # done under dispatch and this point.
        expected=int(time.time() + 30)
        print("expected=%d, expires=%d"%(expected,expires))
        self.assertTrue((expected - expires) < 3 and (expected - expires) >= 0)


        ## Use a token created above as joe by a different user.
        self.db.setCurrentUser('admin')
        url=json_dict['data']['link']
        # strip tracker web prefix leaving leading /.
        url = url[len(self.db.config['TRACKER_WEB'])-1:]
        body_file=BytesIO(body_keyword)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                         headers=headers,
                                         environ=env)
        results = self.server.dispatch('POST',
                                       url,
                                       form)
        print(results)
        self.assertEqual(self.server.client.response_code, 400)
        json_dict = json.loads(b2s(results))
        # get the last component stripping the trailing /
        poe=url[url.rindex('/')+1:]
        self.assertEqual(json_dict['error']['msg'],
                         "POE token '%s' not valid."%poe)

        ## Create POE with bogus lifetime
        body_poe=b'{"lifetime": "10.2" }'
        body_file=BytesIO(body_poe)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            "/rest/data/issue/@poe",
                            form)
        self.assertEqual(self.server.client.response_code, 400)
        print(results)
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['error']['msg'],
                         "Value \'lifetime\' must be an integer specify "
                         "lifetime in seconds. Got 10.2.")

        ## Create POE with lifetime > 1 hour
        body_poe=b'{"lifetime": "3700" }'
        body_file=BytesIO(body_poe)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            "/rest/data/issue/@poe",
                            form)
        self.assertEqual(self.server.client.response_code, 400)
        print(results)
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['error']['msg'],
                         "Value 'lifetime' must be between 1 second and 1 "
                         "hour (3600 seconds). Got 3700.")

        ## Create POE with lifetime < 1 second
        body_poe=b'{"lifetime": "-1" }'
        body_file=BytesIO(body_poe)  # FieldStorage needs a file
        form = client.BinaryFieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.get=self.get_header
        results = self.server.dispatch('POST',
                            "/rest/data/issue/@poe",
                            form)
        self.assertEqual(self.server.client.response_code, 400)
        print(results)
        json_dict = json.loads(b2s(results))
        self.assertEqual(json_dict['error']['msg'],
                         "Value 'lifetime' must be between 1 second and 1 "
                         "hour (3600 seconds). Got -1.")
        del(self.headers)

    def testPutElement(self):
        """
        Change joe's 'realname'
        Check if we can't change admin's detail
        """
        # fail to change Joe's realname via attribute uri
        # no etag
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('data', 'Joe Doe Doe')
        ]
        results = self.server.put_attribute(
            'user', self.joeid, 'realname', form
        )
        self.assertEqual(self.dummy_client.response_code, 412)
        results = self.server.get_attribute(
            'user', self.joeid, 'realname', self.empty_form
        )
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['data'], 'Joe Random')

        # change Joe's realname via attribute uri - etag in header
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.user.getnode(self.joeid),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('data', 'Joe Doe Doe'),
        ]

        self.headers = {'if-match': etag } # use etag in header
        results = self.server.put_attribute(
            'user', self.joeid, 'realname', form
        )
        self.assertEqual(self.dummy_client.response_code, 200)
        results = self.server.get_attribute(
            'user', self.joeid, 'realname', self.empty_form
        )
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['data'], 'Joe Doe Doe')
        del(self.headers)

        # Reset joe's 'realname'. etag in body
        # Also try to set protected items. The protected items should
        # be ignored on put_element to make it easy to get the item
        # with all fields, change one field and put the result without
        # having to filter out protected items.
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.user.getnode(self.joeid),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('creator', '3'),
            cgi.MiniFieldStorage('realname', 'Joe Doe'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.put_element('user', self.joeid, form)
        self.assertEqual(self.dummy_client.response_code, 200)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['realname'], 'Joe Doe')

        # We are joe, so check we can't change admin's details
        results = self.server.put_element('user', '1', form)
        self.assertEqual(self.dummy_client.response_code, 403)
        self.assertEqual(results['error']['status'], 403)

        # Try to reset joe's 'realname' and add a broken prop.
        # This should result in no change to the name and
        # a 400 UsageError stating prop does not exist.
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.user.getnode(self.joeid),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('JustKidding', '3'),
            cgi.MiniFieldStorage('realname', 'Joe Doe'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.put_element('user', self.joeid, form)
        expected= {'error': {'status': 400,
                             'msg': UsageError('Property JustKidding not '
                                               'found in class user')}}
        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(self.dummy_client.response_code, 400)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['realname'], 'Joe Doe')

    def testPutAttribute(self):
        # put protected property
        # make sure we don't have permission issues
        self.db.setCurrentUser('admin')
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.user.getnode(self.joeid),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('data', '3'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.put_attribute(
            'user', self.joeid, 'creator', form
        )
        expected= {'error': {'status': 405, 'msg': 
                             AttributeError('\'"creator", "actor", "creation" and '
                                        '"activity" are reserved\'')}}
        print(results)
        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(self.dummy_client.response_code, 405)

        # put invalid property
        # make sure we don't have permission issues
        self.db.setCurrentUser('admin')
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.user.getnode(self.joeid),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('data', '3'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.put_attribute(
            'user', self.joeid, 'youMustBeKiddingMe', form
        )
        expected= {'error': {'status': 400,
                             'msg': UsageError("'youMustBeKiddingMe' "
                                      "is not a property of user")}}
        print(results)
        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(self.dummy_client.response_code, 400)

    def testPost(self):
        """
        Post a new issue with title: foo
        Verify the information of the created issue
        """
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('title', 'foo')
        ]
        results = self.server.post_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 201)
        issueid = results['data']['id']
        results = self.server.get_element('issue', issueid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['title'], 'foo')
        self.assertEqual(self.db.issue.get(issueid, "tx_Source"), 'web')

    def testPostFile(self):
        """
        Post a new file with content: hello\r\nthere
        Verify the information of the created file
        """
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('content', 'hello\r\nthere')
        ]
        results = self.server.post_collection('file', form)
        self.assertEqual(self.dummy_client.response_code, 201)
        fileid = results['data']['id']
        results = self.server.get_element('file', fileid, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['content'],
            {'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/file1/'})

        # File content is only shown with verbose=3
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@verbose', '3'),
            cgi.MiniFieldStorage('@protected', 'true')
        ]
        results = self.server.get_element('file', fileid, form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['content'], 'hello\r\nthere')
        self.assertIn('creator', results['attributes']) # added by @protected
        self.assertEqual(results['attributes']['creator']['username'], "joe")

    def testAuthDeniedPut(self):
        """
        Test unauthorized PUT request
        """
        # Wrong permissions (caught by roundup security module).
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('realname', 'someone')
        ]
        results = self.server.put_element('user', '1', form)
        self.assertEqual(self.dummy_client.response_code, 403)
        self.assertEqual(results['error']['status'], 403)

    def testAuthDeniedPost(self):
        """
        Test unauthorized POST request
        """
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('username', 'blah')
        ]
        results = self.server.post_collection('user', form)
        self.assertEqual(self.dummy_client.response_code, 403)
        self.assertEqual(results['error']['status'], 403)

    def testAuthAllowedPut(self):
        """
        Test authorized PUT request
        """
        self.db.setCurrentUser('admin')
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('realname', 'someone')
        ]
        try:
            self.server.put_element('user', '2', form)
        except Unauthorised as err:
            self.fail('raised %s' % err)
        finally:
            self.db.setCurrentUser('joe')

    def testAuthAllowedPost(self):
        """
        Test authorized POST request
        """
        self.db.setCurrentUser('admin')
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('username', 'blah')
        ]
        try:
            self.server.post_collection('user', form)
        except Unauthorised as err:
            self.fail('raised %s' % err)
        finally:
            self.db.setCurrentUser('joe')

    def testDeleteAttributeUri(self):
        """
        Test Delete an attribute
        """
        self.maxDiff = 4000
        # create a new issue with userid 1 in the nosy list
        issue_id = self.db.issue.create(title='foo', nosy=['1'])

        # No etag, so this should return 412 - Precondition Failed
        # With no changes
        results = self.server.delete_attribute(
            'issue', issue_id, 'nosy', self.empty_form
        )
        self.assertEqual(self.dummy_client.response_code, 412)
        results = self.server.get_element('issue', issue_id, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 1)
        self.assertListEqual(results['attributes']['nosy'],
            [{'id': '1', 'link': self.url_pfx + 'user/1'}])

        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list.append(cgi.MiniFieldStorage('@etag', etag))
        # remove the title and nosy
        results = self.server.delete_attribute(
            'issue', issue_id, 'title', form
        )
        self.assertEqual(self.dummy_client.response_code, 200)

        del(form.list[-1])
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list.append(cgi.MiniFieldStorage('@etag', etag))
        results = self.server.delete_attribute(
            'issue', issue_id, 'nosy', form
        )
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 0)
        self.assertListEqual(results['attributes']['nosy'], [])
        self.assertEqual(results['attributes']['title'], None)

        # delete protected property
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list.append(cgi.MiniFieldStorage('@etag', etag))
        results = self.server.delete_attribute(
            'issue', issue_id, 'creator', form
        )
        expected= {'error': {
            'status': 405, 
            'msg': AttributeError("Attribute 'creator' can not be updated for class issue.")
        }}

        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(self.dummy_client.response_code, 405)

        # delete required property
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list.append(cgi.MiniFieldStorage('@etag', etag))
        results = self.server.delete_attribute(
            'issue', issue_id, 'requireme', form
        )
        expected= {'error': {'status': 400,
                    'msg': UsageError("Attribute 'requireme' is "
                        "required by class issue and can not be deleted.")}}
        print(results)
        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(str(results['error']['msg']),
                         str(expected['error']['msg']))
        self.assertEqual(self.dummy_client.response_code, 400)

        # delete bogus property
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list.append(cgi.MiniFieldStorage('@etag', etag))
        results = self.server.delete_attribute(
            'issue', issue_id, 'nosuchprop', form
        )
        expected= {'error': {'status': 400,
                    'msg': UsageError("Attribute 'nosuchprop' not valid "
                                      "for class issue.")}}
        print(results)
        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(str(results['error']['msg']),
                         str(expected['error']['msg']))
        self.assertEqual(self.dummy_client.response_code, 400)

    def testPatchAdd(self):
        """
        Test Patch op 'Add'
        """
        # create a new issue with userid 1 in the nosy list
        issue_id = self.db.issue.create(title='foo', nosy=['1'])

        # fail to add userid 2 to the nosy list
        # no etag
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'add'),
            cgi.MiniFieldStorage('nosy', '2')
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 412)

        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'add'),
            cgi.MiniFieldStorage('nosy', '2'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertListEqual(results['attributes']['nosy'], ['1', '2'])

        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'add'),
            cgi.MiniFieldStorage('data', '3'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_attribute('issue', issue_id, 'nosy', form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertListEqual(results['attributes']['nosy'], ['1', '2', '3'])


        # patch with no new_val/data
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'add'),
            cgi.MiniFieldStorage('data', ''),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_attribute('issue', issue_id, 'nosy', form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertListEqual(results['attributes']['nosy'], ['1', '2', '3'])

        # patch invalid property
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'add'),
            cgi.MiniFieldStorage('data', '3'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_attribute('issue', issue_id, 'notGoingToWork', form)
        self.assertEqual(self.dummy_client.response_code, 400)
        print(results)
        expected={'error': {'status': 400,
                            'msg': UsageError(
                                HyperdbValueError(
                            "'notGoingToWork' is not a property of issue",),)}}
        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(str(results['error']['msg']),
                         str(expected['error']['msg']))

    def testPatchReplace(self):
        """
        Test Patch op 'Replace'
        """
        # create a new issue with userid 1 in the nosy list and status = 1
        issue_id = self.db.issue.create(title='foo', nosy=['1'], status='1')

        # fail to replace userid 2 to the nosy list and status = 3
        # no etag.
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'replace'),
            cgi.MiniFieldStorage('nosy', '2'),
            cgi.MiniFieldStorage('status', '3')
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 412)
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['status'], '1')
        self.assertListEqual(results['attributes']['nosy'], ['1'])

        # replace userid 2 to the nosy list and status = 3
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'replace'),
            cgi.MiniFieldStorage('nosy', '2'),
            cgi.MiniFieldStorage('status', '3'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)
        # verify the result
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['status'], '3')
        self.assertListEqual(results['attributes']['nosy'], ['2'])

        # replace status = 2 using status attribute
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'replace'),
            cgi.MiniFieldStorage('data', '2'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_attribute('issue', issue_id, 'status',
                                              form)
        self.assertEqual(self.dummy_client.response_code, 200)
        # verify the result
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['status'], '2')

        # try to set a protected prop. It should fail.
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'replace'),
            cgi.MiniFieldStorage('creator', '2'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        expected= {'error': {'status': 400,
                             'msg': KeyError('"creator", "actor", "creation" and "activity" are reserved',)}}
        print(results)
        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(str(results['error']['msg']),
                         str(expected['error']['msg']))
        self.assertEqual(self.dummy_client.response_code, 400)

        # try to set a protected prop using patch_attribute. It should
        # fail with a 405 bad/unsupported method.
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'replace'),
            cgi.MiniFieldStorage('data', '2'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_attribute('issue', issue_id, 'creator', 
                                              form)
        expected= {'error': {'status': 405,
                             'msg': AttributeError("Attribute 'creator' can not be updated for class issue.",)}}
        print(results)
        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(str(results['error']['msg']),
                         str(expected['error']['msg']))
        self.assertEqual(self.dummy_client.response_code, 405)

    def testPatchRemoveAll(self):
        """
        Test Patch Action 'Remove'
        """
        # create a new issue with userid 1 and 2 in the nosy list
        issue_id = self.db.issue.create(title='foo', nosy=['1', '2'])

        # fail to remove the nosy list and the title
        # no etag
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'remove'),
            cgi.MiniFieldStorage('nosy', ''),
            cgi.MiniFieldStorage('title', '')
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 412)
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['title'], 'foo')
        self.assertEqual(len(results['attributes']['nosy']), 2)
        self.assertEqual(results['attributes']['nosy'], ['1', '2'])

        # remove the nosy list and the title
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('@op', 'remove'),
            cgi.MiniFieldStorage('nosy', ''),
            cgi.MiniFieldStorage('title', ''),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['title'], None)
        self.assertEqual(len(results['attributes']['nosy']), 0)
        self.assertEqual(results['attributes']['nosy'], [])

        # try to remove a protected prop. It should fail.
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'remove'),
            cgi.MiniFieldStorage('creator', '2'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        expected= {'error': {'status': 400,
                             'msg': KeyError('"creator", "actor", "creation" and "activity" are reserved',)}}
        print(results)
        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(str(results['error']['msg']),
                         str(expected['error']['msg']))
        self.assertEqual(self.dummy_client.response_code, 400)

        # try to remove a required prop. it should fail
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('@op', 'remove'),
            cgi.MiniFieldStorage('requireme', ''),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        expected= {'error': {'status': 400,
                             'msg': UsageError("Attribute 'requireme' is required by class issue and can not be removed.")
                             }}
        print(results)
        self.assertEqual(results['error']['status'],
                         expected['error']['status'])
        self.assertEqual(type(results['error']['msg']),
                         type(expected['error']['msg']))
        self.assertEqual(str(results['error']['msg']),
                         str(expected['error']['msg']))
        self.assertEqual(self.dummy_client.response_code, 400)

    def testPatchAction(self):
        """
        Test Patch Action 'Action'
        """
        # create a new issue with userid 1 and 2 in the nosy list
        issue_id = self.db.issue.create(title='foo')

        # fail to execute action retire
        # no etag
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'action'),
            cgi.MiniFieldStorage('@action_name', 'retire')
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 412)
        self.assertFalse(self.db.issue.is_retired(issue_id))

        # execute action retire
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('@op', 'action'),
            cgi.MiniFieldStorage('@action_name', 'retire'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        self.assertTrue(self.db.issue.is_retired(issue_id))

        # execute action restore
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('@op', 'action'),
            cgi.MiniFieldStorage('@action_name', 'restore'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        self.assertTrue(not self.db.issue.is_retired(issue_id))

    def testPatchBadAction(self):
        """
        Test Patch Action 'Unknown'
        """
        # create a new issue with userid 1 and 2 in the nosy list
        issue_id = self.db.issue.create(title='foo')

        # execute action retire
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('@op', 'action'),
            cgi.MiniFieldStorage('@action_name', 'unknown'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 400)
        # verify the result, note order of allowed elements changes
        # for python2/3 so just check prefix.
        self.assertIn('action "unknown" is not supported, allowed: ',
                       results['error']['msg'].args[0])

    def testPatchRemove(self):
        """
        Test Patch Action 'Remove' only some element from a list
        """
        # create a new issue with userid 1, 2, 3 in the nosy list
        issue_id = self.db.issue.create(title='foo', nosy=['1', '2', '3'])

        # fail to remove the nosy list and the title
        # no etag
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'remove'),
            cgi.MiniFieldStorage('nosy', '1, 2'),
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 412)
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 3)
        self.assertEqual(results['attributes']['nosy'], ['1', '2', '3'])

        # remove 1 and 2 from the nosy list
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form.list = [
            cgi.MiniFieldStorage('@op', 'remove'),
            cgi.MiniFieldStorage('nosy', '1, 2'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 1)
        self.assertEqual(results['attributes']['nosy'], ['3'])

        # delete last element: 3
        etag = calculate_etag(self.db.issue.getnode(issue_id),
                              self.db.config['WEB_SECRET_KEY'])
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('@op', 'remove'),
            cgi.MiniFieldStorage('data', '3'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_attribute('issue', issue_id, 'nosy', form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.terse_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 0)
        self.assertListEqual(results['attributes']['nosy'], [])

    @skip_jwt
    def test_expired_jwt(self):
        # self.dummy_client.main() closes database, so
        # we need a new test with setup called for each test
        out = []
        def wh(s):
            out.append(s)

        secret = self.db.config.WEB_JWT_SECRET

        # verify library and tokens are correct
        self.assertRaises(jwt.exceptions.InvalidTokenError,
                          jwt.decode, self.jwt['expired'],
                          secret,  algorithms=['HS256'],
                          audience=self.db.config.TRACKER_WEB,
                          issuer=self.db.config.TRACKER_WEB)

        result = jwt.decode(self.jwt['user'],
                            secret,  algorithms=['HS256'],
                            audience=self.db.config.TRACKER_WEB,
                            issuer=self.db.config.TRACKER_WEB)
        self.assertEqual(self.claim['user'],result)

        result = jwt.decode(self.jwt['user:email'],
                            secret,  algorithms=['HS256'],
                            audience=self.db.config.TRACKER_WEB,
                            issuer=self.db.config.TRACKER_WEB)
        self.assertEqual(self.claim['user:email'],result)

        # set environment for all jwt tests
        env = {
            'PATH_INFO': 'rest/data/user',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest',
            "REQUEST_METHOD": "GET"
        }
        self.dummy_client = client.Client(self.instance, MockNull(), env,
                                          [], None)
        self.dummy_client.db = self.db
        self.dummy_client.request.headers.get = self.get_header
        self.empty_form = cgi.FieldStorage()
        self.terse_form = cgi.FieldStorage()
        self.terse_form.list = [
            cgi.MiniFieldStorage('@verbose', '0'),
        ]
        self.dummy_client.form = cgi.FieldStorage()
        self.dummy_client.form.list = [
            cgi.MiniFieldStorage('@fields', 'username,address'),
        ]
        # accumulate json output for further analysis
        self.dummy_client.write = wh

        # set up for expired token first
        env['HTTP_AUTHORIZATION'] = 'bearer %s'%self.jwt['expired']
        self.dummy_client.main()

        # this will be the admin still as auth failed
        self.assertEqual('1', self.db.getuid())
        self.assertEqual(out[0], b'Invalid Login - Signature has expired')
        del(out[0])


    @skip_jwt
    def test_user_jwt(self):
        # self.dummy_client.main() closes database, so
        # we need a new test with setup called for each test
        out = []
        def wh(s):
            out.append(s)

        secret = self.db.config.WEB_JWT_SECRET

        # verify library and tokens are correct
        self.assertRaises(jwt.exceptions.InvalidTokenError,
                          jwt.decode, self.jwt['expired'],
                          secret,  algorithms=['HS256'],
                          audience=self.db.config.TRACKER_WEB,
                          issuer=self.db.config.TRACKER_WEB)

        result = jwt.decode(self.jwt['user'],
                            secret,  algorithms=['HS256'],
                            audience=self.db.config.TRACKER_WEB,
                            issuer=self.db.config.TRACKER_WEB)
        self.assertEqual(self.claim['user'],result)

        result = jwt.decode(self.jwt['user:email'],
                            secret,  algorithms=['HS256'],
                            audience=self.db.config.TRACKER_WEB,
                            issuer=self.db.config.TRACKER_WEB)
        self.assertEqual(self.claim['user:email'],result)

        # set environment for all jwt tests
        env = {
            'PATH_INFO': 'rest/data/user',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest',
            "REQUEST_METHOD": "GET"
        }
        self.dummy_client = client.Client(self.instance, MockNull(), env,
                                          [], None)
        self.dummy_client.db = self.db
        self.dummy_client.request.headers.get = self.get_header
        self.empty_form = cgi.FieldStorage()
        self.terse_form = cgi.FieldStorage()
        self.terse_form.list = [
            cgi.MiniFieldStorage('@verbose', '0'),
        ]
        self.dummy_client.form = cgi.FieldStorage()
        self.dummy_client.form.list = [
            cgi.MiniFieldStorage('@fields', 'username,address'),
        ]
        # accumulate json output for further analysis
        self.dummy_client.write = wh

        # set up for standard user role token
        env['HTTP_AUTHORIZATION'] = 'bearer %s'%self.jwt['user']
        self.dummy_client.main()
        print(out[0])
        json_dict = json.loads(b2s(out[0]))
        print(json_dict)
        # user will be joe id 3 as auth works
        self.assertTrue('3', self.db.getuid())
        # there should be three items in the collection admin, anon, and joe
        self.assertEqual(3, len(json_dict['data']['collection']))
        # since this token has no access to email addresses, only joe
        # should have email addresses. Order is by id by default.
        self.assertFalse('address' in json_dict['data']['collection'][0])
        self.assertFalse('address' in json_dict['data']['collection'][1])
        self.assertTrue('address' in json_dict['data']['collection'][2])
        del(out[0])
        self.db.setCurrentUser('admin')

    @skip_jwt
    def test_user_email_jwt(self):
        '''tests "Rest Access" permission present case'''
        # self.dummy_client.main() closes database, so
        # we need a new test with setup called for each test
        out = []
        def wh(s):
            out.append(s)

        secret = self.db.config.WEB_JWT_SECRET

        # verify library and tokens are correct
        self.assertRaises(jwt.exceptions.InvalidTokenError,
                          jwt.decode, self.jwt['expired'],
                          secret,  algorithms=['HS256'],
                          audience=self.db.config.TRACKER_WEB,
                          issuer=self.db.config.TRACKER_WEB)

        result = jwt.decode(self.jwt['user'],
                            secret,  algorithms=['HS256'],
                            audience=self.db.config.TRACKER_WEB,
                            issuer=self.db.config.TRACKER_WEB)
        self.assertEqual(self.claim['user'],result)

        result = jwt.decode(self.jwt['user:email'],
                            secret,  algorithms=['HS256'],
                            audience=self.db.config.TRACKER_WEB,
                            issuer=self.db.config.TRACKER_WEB)
        self.assertEqual(self.claim['user:email'],result)

        # set environment for all jwt tests
        env = {
            'PATH_INFO': 'rest/data/user',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest',
            "REQUEST_METHOD": "GET"
        }
        self.dummy_client = client.Client(self.instance, MockNull(), env,
                                          [], None)
        self.dummy_client.db = self.db
        self.dummy_client.request.headers.get = self.get_header
        self.empty_form = cgi.FieldStorage()
        self.terse_form = cgi.FieldStorage()
        self.terse_form.list = [
            cgi.MiniFieldStorage('@verbose', '0'),
        ]
        self.dummy_client.form = cgi.FieldStorage()
        self.dummy_client.form.list = [
            cgi.MiniFieldStorage('@fields', 'username,address'),
        ]
        # accumulate json output for further analysis
        self.dummy_client.write = wh

        # set up for limited user:email role token
        env['HTTP_AUTHORIZATION'] = 'bearer %s'%self.jwt['user:email']
        self.dummy_client.main()
        json_dict = json.loads(b2s(out[0]))
        print(json_dict)
        # user will be joe id 3 as auth works
        self.assertTrue('3', self.db.getuid())
        # there should be three items in the collection admin, anon, and joe
        self.assertEqual(3, len(json_dict['data']['collection']))
        # However this token has access to email addresses, so all three
        # should have email addresses. Order is by id by default.
        self.assertTrue('address' in json_dict['data']['collection'][0])
        self.assertTrue('address' in json_dict['data']['collection'][1])
        self.assertTrue('address' in json_dict['data']['collection'][2])

    @skip_jwt
    def test_user_emailnorest_jwt(self):
        '''tests "Rest Access" permission missing case'''
        # self.dummy_client.main() closes database, so
        # we need a new test with setup called for each test
        out = []
        def wh(s):
            out.append(s)

        secret = self.db.config.WEB_JWT_SECRET

        # verify library and tokens are correct
        self.assertRaises(jwt.exceptions.InvalidTokenError,
                          jwt.decode, self.jwt['expired'],
                          secret,  algorithms=['HS256'],
                          audience=self.db.config.TRACKER_WEB,
                          issuer=self.db.config.TRACKER_WEB)

        result = jwt.decode(self.jwt['user'],
                            secret,  algorithms=['HS256'],
                            audience=self.db.config.TRACKER_WEB,
                            issuer=self.db.config.TRACKER_WEB)
        self.assertEqual(self.claim['user'],result)

        result = jwt.decode(self.jwt['user:email'],
                            secret,  algorithms=['HS256'],
                            audience=self.db.config.TRACKER_WEB,
                            issuer=self.db.config.TRACKER_WEB)
        self.assertEqual(self.claim['user:email'],result)

        # set environment for all jwt tests
        env = {
            'PATH_INFO': 'rest/data/user',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest',
            "REQUEST_METHOD": "GET"
        }
        self.dummy_client = client.Client(self.instance, MockNull(), env,
                                          [], None)
        self.dummy_client.db = self.db
        self.dummy_client.request.headers.get = self.get_header
        self.empty_form = cgi.FieldStorage()
        self.terse_form = cgi.FieldStorage()
        self.terse_form.list = [
            cgi.MiniFieldStorage('@verbose', '0'),
        ]
        self.dummy_client.form = cgi.FieldStorage()
        self.dummy_client.form.list = [
            cgi.MiniFieldStorage('@fields', 'username,address'),
        ]
        # accumulate json output for further analysis
        self.dummy_client.write = wh

        # set up for limited user:email role token
        env['HTTP_AUTHORIZATION'] = 'bearer %s'%self.jwt['user:emailnorest']
        self.dummy_client.main()
        json_dict = json.loads(b2s(out[0]))
        # user will be joe id 3 as auth works
        self.assertTrue('1', self.db.getuid())
        { "error": { "status": 403, "msg": "Forbidden." } }
        self.assertTrue('error' in json_dict)
        self.assertTrue(json_dict['error']['status'], 403)
        self.assertTrue(json_dict['error']['msg'], "Forbidden.")

    @skip_jwt
    def test_disabled_jwt(self):
        # self.dummy_client.main() closes database, so
        # we need a new test with setup called for each test
        out = []
        def wh(s):
            out.append(s)

        # set environment for all jwt tests
        env = {
            'PATH_INFO': 'rest/data/user',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest',
            "REQUEST_METHOD": "GET"
        }
        self.dummy_client = client.Client(self.instance, MockNull(), env,
                                          [], None)
        self.dummy_client.db = self.db
        self.dummy_client.request.headers.get = self.get_header
        self.empty_form = cgi.FieldStorage()
        self.terse_form = cgi.FieldStorage()
        self.terse_form.list = [
            cgi.MiniFieldStorage('@verbose', '0'),
        ]
        self.dummy_client.form = cgi.FieldStorage()
        self.dummy_client.form.list = [
            cgi.MiniFieldStorage('@fields', 'username,address'),
        ]
        # accumulate json output for further analysis
        self.dummy_client.write = wh
        # disable jwt validation by making secret too short
        # use the default value for this in configure.py.
        self.db.config['WEB_JWT_SECRET'] = "disabled"
        env['HTTP_AUTHORIZATION'] = 'bearer %s'%self.jwt['user']
        self.dummy_client.main()
        # user will be 1 as there is no auth
        self.assertTrue('1', self.db.getuid())
        self.assertEqual(out[0], b'Invalid Login - Support for jwt disabled by admin.')

    @skip_jwt
    def test_bad_issue_jwt(self):
        # self.dummy_client.main() closes database, so
        # we need a new test with setup called for each test
        out = []
        def wh(s):
            out.append(s)

        # set environment for all jwt tests
        env = {
            'PATH_INFO': 'rest/data/user',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest',
            "REQUEST_METHOD": "GET"
        }
        self.dummy_client = client.Client(self.instance, MockNull(), env,
                                          [], None)
        self.dummy_client.db = self.db
        self.dummy_client.request.headers.get = self.get_header
        self.empty_form = cgi.FieldStorage()
        self.terse_form = cgi.FieldStorage()
        self.terse_form.list = [
            cgi.MiniFieldStorage('@verbose', '0'),
        ]
        self.dummy_client.form = cgi.FieldStorage()
        self.dummy_client.form.list = [
            cgi.MiniFieldStorage('@fields', 'username,address'),
        ]
        # accumulate json output for further analysis
        self.dummy_client.write = wh
        env['HTTP_AUTHORIZATION'] = 'bearer %s'%self.jwt['badiss']
        self.dummy_client.main()
        # user will be 1 as there is no auth
        self.assertTrue('1', self.db.getuid())
        self.assertEqual(out[0], b'Invalid Login - Invalid issuer')

    @skip_jwt
    def test_bad_audience_jwt(self):
        # self.dummy_client.main() closes database, so
        # we need a new test with setup called for each test
        out = []
        def wh(s):
            out.append(s)

        # set environment for all jwt tests
        env = {
            'PATH_INFO': 'rest/data/user',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest',
            "REQUEST_METHOD": "GET"
        }
        self.dummy_client = client.Client(self.instance, MockNull(), env,
                                          [], None)
        self.dummy_client.db = self.db
        self.dummy_client.request.headers.get = self.get_header
        self.empty_form = cgi.FieldStorage()
        self.terse_form = cgi.FieldStorage()
        self.terse_form.list = [
            cgi.MiniFieldStorage('@verbose', '0'),
        ]
        self.dummy_client.form = cgi.FieldStorage()
        self.dummy_client.form.list = [
            cgi.MiniFieldStorage('@fields', 'username,address'),
        ]
        # accumulate json output for further analysis
        self.dummy_client.write = wh
        env['HTTP_AUTHORIZATION'] = 'bearer %s'%self.jwt['badaud']
        self.dummy_client.main()
        # user will be 1 as there is no auth
        self.assertTrue('1', self.db.getuid())
        self.assertEqual(out[0], b'Invalid Login - Invalid audience')

    @skip_jwt
    def test_bad_roles_jwt(self):
        # self.dummy_client.main() closes database, so
        # we need a new test with setup called for each test
        out = []
        def wh(s):
            out.append(s)

        # set environment for all jwt tests
        env = {
            'PATH_INFO': 'rest/data/user',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest',
            "REQUEST_METHOD": "GET"
        }
        self.dummy_client = client.Client(self.instance, MockNull(), env,
                                          [], None)
        self.dummy_client.db = self.db
        self.dummy_client.request.headers.get = self.get_header
        self.empty_form = cgi.FieldStorage()
        self.terse_form = cgi.FieldStorage()
        self.terse_form.list = [
            cgi.MiniFieldStorage('@verbose', '0'),
        ]
        self.dummy_client.form = cgi.FieldStorage()
        self.dummy_client.form.list = [
            cgi.MiniFieldStorage('@fields', 'username,address'),
        ]
        # accumulate json output for further analysis
        self.dummy_client.write = wh
        env['HTTP_AUTHORIZATION'] = 'bearer %s'%self.jwt['badroles']
        self.dummy_client.main()
        # user will be 1 as there is no auth
        self.assertTrue('1', self.db.getuid())
        self.assertEqual(out[0], b'Invalid Login - Token roles are invalid.')

    @skip_jwt
    def test_bad_subject_jwt(self):
        # self.dummy_client.main() closes database, so
        # we need a new test with setup called for each test
        out = []
        def wh(s):
            out.append(s)

        # set environment for all jwt tests
        env = {
            'PATH_INFO': 'rest/data/user',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest',
            "REQUEST_METHOD": "GET"
        }
        self.dummy_client = client.Client(self.instance, MockNull(), env,
                                          [], None)
        self.dummy_client.db = self.db
        self.dummy_client.request.headers.get = self.get_header
        self.empty_form = cgi.FieldStorage()
        self.terse_form = cgi.FieldStorage()
        self.terse_form.list = [
            cgi.MiniFieldStorage('@verbose', '0'),
        ]
        self.dummy_client.form = cgi.FieldStorage()
        self.dummy_client.form.list = [
            cgi.MiniFieldStorage('@fields', 'username,address'),
        ]
        # accumulate json output for further analysis
        self.dummy_client.write = wh
        env['HTTP_AUTHORIZATION'] = 'bearer %s'%self.jwt['badsub']
        self.dummy_client.main()
        # user will be 1 as there is no auth
        self.assertTrue('1', self.db.getuid())
        self.assertEqual(out[0], b'Invalid Login - Token subject is invalid.')

def get_obj(path, id):
    return {
        'id': id,
        'link': path + id
    }

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)
