import unittest
import os
import shutil
import errno

from time import sleep
from datetime import datetime

from roundup.cgi.exceptions import *
from roundup.hyperdb import HyperdbValueError
from roundup.exceptions import *
from roundup import password, hyperdb
from roundup.rest import RestfulInstance, calculate_etag
from roundup.backends import list_backends
from roundup.cgi import client
from roundup.anypy.strings import b2s, s2b
import random

from roundup.backends.sessions_dbm import OneTimeKeys
from roundup.anypy.dbm_ import anydbm, whichdb

from .db_test_base import setupTracker

from .mocknull import MockNull

from io import BytesIO
import json

NEEDS_INSTANCE = 1


class TestCase():

    backend = None
    url_pfx = 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/'

    def setUp(self):
        self.dirname = '_test_rest'
        # set up and open a tracker
        self.instance = setupTracker(self.dirname, self.backend)

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

        self.db.commit()
        self.db.close()
        self.db = self.instance.open('joe')
        # Allow joe to retire
        p = self.db.security.addPermission(name='Retire', klass='issue')
        self.db.security.addPermissionToRole('User', p)

        self.db.tx_Source = 'web'

        self.db.issue.addprop(tx_Source=hyperdb.String())
        self.db.issue.addprop(anint=hyperdb.Integer())
        self.db.issue.addprop(afloat=hyperdb.Number())
        self.db.issue.addprop(abool=hyperdb.Boolean())
        self.db.issue.addprop(requireme=hyperdb.String(required=True))
        self.db.msg.addprop(tx_Source=hyperdb.String())

        self.db.post_init()

        thisdir = os.path.dirname(__file__)
        vars = {}
        with open(os.path.join(thisdir, "tx_Source_detector.py")) as f:
            code = compile(f.read(), "tx_Source_detector.py", "exec")
            exec(code, vars)
        vars['init'](self.db)

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

    def testOutputFormat(self):
        """ test of @fields and @verbose implementation """

        self.maxDiff = 4000
        # create sample data
        try:
            self.db.status.create(name='open')
        except ValueError:
            pass
        try:
            self.db.status.create(name='closed')
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
        base_path = self.db.config['TRACKER_WEB'] + 'rest/data/issue/'


        # Check formating for issues status=open; @fields and verbose tests
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('status', 'open'),
            cgi.MiniFieldStorage('@fields', 'nosy,status'),
            cgi.MiniFieldStorage('@verbose', '2')
        ]

        expected={'data':
                   {'@total_size': 3,
                    'collection': [
                        {'status': {'id': '9',
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
                        {'status': {
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
                        {'status': {
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
            cgi.MiniFieldStorage('@fields', 'queries,password'),
            cgi.MiniFieldStorage('@verbose', '2')
        ]
        expected = {'data': {
            'id': '3',
            'type': 'user',
            '@etag': '',
            'link': 'http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/user/3',
            'attributes': {
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

    def testFilter(self):
        """
        Retrieve all three users
        obtain data for 'joe'
        """
        # create sample data
        try:
            self.db.status.create(name='open')
        except ValueError:
            pass
        try:
            self.db.status.create(name='closed')
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
            title='foo2',
            status=self.db.status.lookup('open'),
            priority=self.db.priority.lookup('normal')
        )
        issue_closed_norm = self.db.issue.create(
            title='foo3',
            status=self.db.status.lookup('closed'),
            priority=self.db.priority.lookup('normal')
        )
        issue_closed_crit = self.db.issue.create(
            title='foo4',
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
                self.db.config['WEB_API_CALLS_PER_INTERVAL'] -1 - i
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
            self.db.config['WEB_API_CALLS_PER_INTERVAL'])
        self.assertEqual(
            self.server.client.additional_headers["X-RateLimit-Limit-Period"],
            self.db.config['WEB_API_INTERVAL_IN_SEC'])
        self.assertEqual(
            self.server.client.additional_headers["X-RateLimit-Remaining"],
            0)
        # value will be almost 60. Allow 1-2 seconds for all 20 rounds.
        self.assertAlmostEqual(
            self.server.client.additional_headers["X-RateLimit-Reset"],
            59, delta=1)
        self.assertEqual(
            str(self.server.client.additional_headers["Retry-After"]),
            "3.0")  # check as string

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
            self.db.config['WEB_API_CALLS_PER_INTERVAL'])
        self.assertEqual(
            self.server.client.additional_headers["X-RateLimit-Limit-Period"],
            self.db.config['WEB_API_INTERVAL_IN_SEC'])
        self.assertEqual(
            self.server.client.additional_headers["X-RateLimit-Remaining"],
            0)
        self.assertFalse("Retry-After" in
                         self.server.client.additional_headers) 
        # we still need to wait a minute for everything to clear
        self.assertAlmostEqual(
            self.server.client.additional_headers["X-RateLimit-Reset"],
            59, delta=1)

        # and make sure we need to wait another three seconds
        # as we consumed the last api call
        results = self.server.dispatch('GET',
                     "/rest/data/user/%s/realname"%self.joeid,
                            self.empty_form)

        self.assertEqual(self.server.client.response_code, 429)
        self.assertEqual(
            str(self.server.client.additional_headers["Retry-After"]),
            "3.0")  # check as string

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
            self.assertEqual(etag, '"0433784660a141e8262835171e70fd2f"')

            # modify key and verify we have a different etag
            etag = calculate_etag(node, self.db.config['WEB_SECRET_KEY'] + "a")
            items = node.items(protected=True) # include every item
            print(repr(sorted(items)))
            print(etag)
            self.assertNotEqual(etag, '"0433784660a141e8262835171e70fd2f"')

            # change data and verify we have a different etag
            node.username="Paul"
            etag = calculate_etag(node, self.db.config['WEB_SECRET_KEY'])
            items = node.items(protected=True) # include every item
            print(repr(sorted(items)))
            print(etag)
            self.assertEqual(etag, '"8abeacd284d58655c620d60389e29d4d"')
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
        # DELETE: delete issue 1
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
        json_dict = json.loads(b2s(results))
        print(results)
        status=json_dict['data']['status']
        self.assertEqual(status, 'ok')

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
        print(results)
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
        print(results)
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
        print(results)
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
        print(results)
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
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        results_dict = json.loads(b2s(results))
        self.assertEqual(results_dict, expected_rest)


        results = self.server.dispatch('GET',
                            "/rest/", self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        results_dict = json.loads(b2s(results))
        self.assertEqual(results_dict, expected_rest)

        results = self.server.dispatch('GET',
                            "/rest/summary", self.empty_form)
        print(results)
        self.assertEqual(self.server.client.response_code, 200)

        results = self.server.dispatch('GET',
                            "/rest/summary/", self.empty_form)
        print(results)
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
        print(results)
        self.assertEqual(self.server.client.response_code, 200)
        results_dict = json.loads(b2s(results))
        self.assertEqual(results_dict, expected_data)

        results = self.server.dispatch('GET',
                            "/rest/data/", self.empty_form)
        print(results)
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
            cgi.MiniFieldStorage('@verbose', '3')
        ]
        results = self.server.get_element('file', fileid, form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['content'], 'hello\r\nthere')

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
        self.assertEqual(len(results['attributes']['nosy']), 2)
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
        self.assertEqual(len(results['attributes']['nosy']), 3)
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
        self.assertEqual(len(results['attributes']['nosy']), 3)
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
        self.assertEqual(len(results['attributes']['nosy']), 1)
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
        self.assertEqual(len(results['attributes']['nosy']), 1)
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


def get_obj(path, id):
    return {
        'id': id,
        'link': path + id
    }

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)
