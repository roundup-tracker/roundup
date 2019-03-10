import unittest
import os
import shutil
import errno

from roundup.cgi.exceptions import *
from roundup import password, hyperdb
from roundup.rest import RestfulInstance, calculate_etag
from roundup.backends import list_backends
from roundup.cgi import client
import random

from .db_test_base import setupTracker

from .mocknull import MockNull

from io import StringIO
import json

NEEDS_INSTANCE = 1


class TestCase():

    backend = None

    def setUp(self):
        self.dirname = '_test_rest'
        # set up and open a tracker
        self.instance = setupTracker(self.dirname, self.backend)

        # open the database
        self.db = self.instance.open('admin')

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
        self.dummy_client.request.headers.getheader = self.get_header
        self.empty_form = cgi.FieldStorage()

        self.server = RestfulInstance(self.dummy_client, self.db)

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
        except (AttributeError, KeyError):
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

        # Obtain data for 'joe'.
        results = self.server.get_attribute(
            'user', self.joeid, 'username', self.empty_form
        )
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['data'], 'joe')

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
            cgi.MiniFieldStorage('where_status', 'open')
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
            cgi.MiniFieldStorage('where_status', 'closed'),
            cgi.MiniFieldStorage('where_priority', 'critical')
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
            cgi.MiniFieldStorage('where_status', 'closed'),
            cgi.MiniFieldStorage('where_priority', 'normal,critical')
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
            cgi.MiniFieldStorage('page_size', page_size),
            cgi.MiniFieldStorage('page_index', 1)
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
                         "%s?page_index=1&page_size=%s"%(base_url,page_size))
        self.assertEqual(results['data']['@links']['next'][0]['uri'],
                         "%s?page_index=2&page_size=%s"%(base_url,page_size))

        page_one_results = results # save this for later

        # Retrieve page 2
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('page_size', page_size),
            cgi.MiniFieldStorage('page_index', 2)
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['data']['collection']), page_two_expected)
        self.assertTrue('@links' in results['data'])
        self.assertTrue('self' in results['data']['@links'])
        self.assertTrue('next' in results['data']['@links'])
        self.assertTrue('prev' in results['data']['@links'])
        self.assertEqual(results['data']['@links']['self'][0]['uri'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue?page_index=2&page_size=%s"%page_size)
        self.assertEqual(results['data']['@links']['next'][0]['uri'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue?page_index=3&page_size=%s"%page_size)
        self.assertEqual(results['data']['@links']['prev'][0]['uri'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue?page_index=1&page_size=%s"%page_size)
        self.assertEqual(results['data']['@links']['self'][0]['rel'],
                         'self')
        self.assertEqual(results['data']['@links']['next'][0]['rel'],
                         'next')
        self.assertEqual(results['data']['@links']['prev'][0]['rel'],
                         'prev')

        # Retrieve page 3
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('page_size', page_size),
            cgi.MiniFieldStorage('page_index', 3)
        ]
        results = self.server.get_collection('issue', form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['data']['collection']), page_three_expected)
        self.assertTrue('@links' in results['data'])
        self.assertTrue('self' in results['data']['@links'])
        self.assertFalse('next' in results['data']['@links'])
        self.assertTrue('prev' in results['data']['@links'])
        self.assertEqual(results['data']['@links']['self'][0]['uri'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue?page_index=3&page_size=%s"%page_size)
        self.assertEqual(results['data']['@links']['prev'][0]['uri'],
                         "http://tracker.example/cgi-bin/roundup.cgi/bugs/rest/data/issue?page_index=2&page_size=%s"%page_size)

        # Verify that page_index is optional
        # Should start at page 1
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('page_size', page_size),
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

    def testEtagProcessing(self):
        '''
        Etags can come from two places:
           ETag http header
           @etags value posted in the form

        Both will be checked if availble. If either one
        fails, the etag check will fail.

        Run over header only, etag in form only, both,
        each one broke and no etag. Use the put command
        to triger the etag checking code.
        '''
        for mode in ('header', 'etag', 'both',
                     'brokenheader', 'brokenetag', 'none'):
            try:
                # clean up any old header
                del(self.headers)
            except AttributeError:
                pass

            form = cgi.FieldStorage()
            etag = calculate_etag(self.db.user.getnode(self.joeid))
            form.list = [
                cgi.MiniFieldStorage('data', 'Joe Doe Doe'),
            ]

            if mode == 'header':
                print("Mode = %s"%mode)
                self.headers = {'etag': etag}
            elif mode == 'etag':
                print("Mode = %s"%mode)
                form.list.append(cgi.MiniFieldStorage('@etag', etag))
            elif mode == 'both':
                print("Mode = %s"%mode)
                self.headers = {'etag': etag}
                form.list.append(cgi.MiniFieldStorage('@etag', etag))
            elif mode == 'brokenheader':
                print("Mode = %s"%mode)
                self.headers = {'etag': 'bad'}
                form.list.append(cgi.MiniFieldStorage('@etag', etag))
            elif mode == 'brokenetag':
                print("Mode = %s"%mode)
                self.headers = {'etag': etag}
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

    def testDispatch(self):
        """
        run changes through rest dispatch(). This also tests
        sending json payload through code as dispatch is the
        code that changes json payload into something we can
        process.
        """
        # Set joe's 'realname' using json data.
        # simulate: /rest/data/user/<id>/realname
        # use etag in header
        etag = calculate_etag(self.db.user.getnode(self.joeid))
        body=u'{ "data": "Joe Doe 1" }'
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "PUT"
        }
        headers={"accept": "application/json",
                 "content-type": env['CONTENT_TYPE'],
                 "etag": etag
        }
        self.headers=headers
        # we need to generate a FieldStorage the looks like
        #  FieldStorage(None, None, 'string') rather than
        #  FieldStorage(None, None, [])
        body_file=StringIO(body)  # FieldStorage needs a file
        form = cgi.FieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.getheader=self.get_header
        results = self.server.dispatch('PUT',
                            "/rest/data/user/%s/realname"%self.joeid,
                            form)

        self.assertEqual(self.server.client.response_code, 200)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['realname'],
                         'Joe Doe 1')
        del(self.headers)

        # Set joe's 'realname' using json data.
        # simulate: /rest/data/user/<id>/realname
        # use etag in payload
        etag = calculate_etag(self.db.user.getnode(self.joeid))
        body=u'{ "@etag": "%s", "data": "Joe Doe 2" }'%etag
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "PUT"
        }
        headers={"accept": "application/json",
                 "content-type": env['CONTENT_TYPE']
        }
        self.headers=headers
        body_file=StringIO(body)  # FieldStorage needs a file
        form = cgi.FieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.getheader=self.get_header
        results = self.server.dispatch('PUT',
                            "/rest/data/user/%s/realname"%self.joeid,
                            form)

        self.assertEqual(self.server.client.response_code, 200)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['realname'],
                         'Joe Doe 2')
        del(self.headers)

        # change Joe's realname via a normal web form
        # This generates a FieldStorage that looks like:
        #  FieldStorage(None, None, [])
        # use etag from header
        #
        # also use a GET on the uri via the dispatch to get
        # the results from the db.
        etag = calculate_etag(self.db.user.getnode(self.joeid))
        headers={"etag": etag,
                 "accept": "application/json",
        }
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('data', 'Joe Doe'),
        ]
        self.headers = headers
        self.server.client.request.headers.getheader = self.get_header
        results = self.server.dispatch('PUT',
                            "/rest/data/user/%s/realname"%self.joeid,
                            form)
        self.assertEqual(self.dummy_client.response_code, 200)
        results = self.server.dispatch('GET',
                            "/rest/data/user/%s/realname"%self.joeid,
                                       self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        json_dict = json.loads(results)

        self.assertEqual(json_dict['data']['data'], 'Joe Doe')
        self.assertEqual(json_dict['data']['link'],
                         "http://tracker.example/cgi-bin/"
                         "roundup.cgi/bugs/rest/data/user/3/realname") 
        self.assertEqual(json_dict['data']['type'], "<type 'str'>")
        self.assertEqual(json_dict['data']["id"], "3")
        del(self.headers)


        # PATCH joe's email address with json
        # save address so we can use it later
        stored_results = self.server.get_element('user', self.joeid,
                                                 self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)

        etag = calculate_etag(self.db.user.getnode(self.joeid))
        body=u'{ "address": "demo2@example.com", "@etag": "%s"}'%etag
        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "PATCH"
        }
        headers={"accept": "application/json",
                 "content-type": env['CONTENT_TYPE']
        }
        self.headers=headers
        body_file=StringIO(body)  # FieldStorage needs a file
        form = cgi.FieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.getheader=self.get_header
        results = self.server.dispatch('PATCH',
                            "/rest/data/user/%s"%self.joeid,
                            form)

        self.assertEqual(self.server.client.response_code, 200)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['address'],
                         'demo2@example.com')

        # and set it back
        etag = calculate_etag(self.db.user.getnode(self.joeid))
        body=u'{ "address": "%s", "@etag": "%s"}'%(
            stored_results['data']['attributes']['address'],
            etag)
        # reuse env and headers from prior test.
        body_file=StringIO(body)  # FieldStorage needs a file
        form = cgi.FieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.getheader=self.get_header
        results = self.server.dispatch('PATCH',
                            "/rest/data/user/%s"%self.joeid,
                            form)

        self.assertEqual(self.server.client.response_code, 200)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['address'],
                         'random@home.org')
        del(self.headers)

        # POST to create new issue
        body=u'{ "title": "foo bar", "priority": "critical" }'

        env = { "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": len(body),
                "REQUEST_METHOD": "POST"
        }
        headers={"accept": "application/json",
                 "content-type": env['CONTENT_TYPE']
        }
        self.headers=headers
        body_file=StringIO(body)  # FieldStorage needs a file
        form = cgi.FieldStorage(body_file,
                                headers=headers,
                                environ=env)
        self.server.client.request.headers.getheader=self.get_header
        results = self.server.dispatch('POST',
                            "/rest/data/issue",
                            form)

        self.assertEqual(self.server.client.response_code, 201)
        json_dict = json.loads(results)
        issue_id=json_dict['data']['id']
        results = self.server.get_element('issue',
                            str(issue_id), # must be a string not unicode
                            self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['title'],
                         'foo bar')
        del(self.headers)

    def testPut(self):
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
        etag = calculate_etag(self.db.user.getnode(self.joeid))
        form.list = [
            cgi.MiniFieldStorage('data', 'Joe Doe Doe'),
        ]

        self.headers = {'etag': etag } # use etag in header
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
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.user.getnode(self.joeid))
        form.list = [
            cgi.MiniFieldStorage('realname', 'Joe Doe'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.put_element('user', self.joeid, form)
        self.assertEqual(self.dummy_client.response_code, 200)
        results = self.server.get_element('user', self.joeid, self.empty_form)
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['data']['attributes']['realname'], 'Joe Doe')

        # check we can't change admin's details
        results = self.server.put_element('user', '1', form)
        self.assertEqual(self.dummy_client.response_code, 403)
        self.assertEqual(results['error']['status'], 403)

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
        self.assertListEqual(results['attributes']['nosy'], ['1'])

        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.issue.getnode(issue_id))
        form.list.append(cgi.MiniFieldStorage('@etag', etag))
        # remove the title and nosy
        results = self.server.delete_attribute(
            'issue', issue_id, 'title', form
        )
        self.assertEqual(self.dummy_client.response_code, 200)

        del(form.list[-1])
        etag = calculate_etag(self.db.issue.getnode(issue_id))
        form.list.append(cgi.MiniFieldStorage('@etag', etag))
        results = self.server.delete_attribute(
            'issue', issue_id, 'nosy', form
        )
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 0)
        self.assertListEqual(results['attributes']['nosy'], [])
        self.assertEqual(results['attributes']['title'], None)

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
            cgi.MiniFieldStorage('op', 'add'),
            cgi.MiniFieldStorage('nosy', '2')
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 412)

        etag = calculate_etag(self.db.issue.getnode(issue_id))
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('op', 'add'),
            cgi.MiniFieldStorage('nosy', '2'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 2)
        self.assertListEqual(results['attributes']['nosy'], ['1', '2'])

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
            cgi.MiniFieldStorage('op', 'replace'),
            cgi.MiniFieldStorage('nosy', '2'),
            cgi.MiniFieldStorage('status', '3')
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 412)
        results = self.server.get_element('issue', issue_id, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['status'], '1')
        self.assertEqual(len(results['attributes']['nosy']), 1)
        self.assertListEqual(results['attributes']['nosy'], ['1'])

        # replace userid 2 to the nosy list and status = 3
        etag = calculate_etag(self.db.issue.getnode(issue_id))
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('op', 'replace'),
            cgi.MiniFieldStorage('nosy', '2'),
            cgi.MiniFieldStorage('status', '3'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)
        # verify the result
        results = self.server.get_element('issue', issue_id, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['status'], '3')
        self.assertEqual(len(results['attributes']['nosy']), 1)
        self.assertListEqual(results['attributes']['nosy'], ['2'])

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
            cgi.MiniFieldStorage('op', 'remove'),
            cgi.MiniFieldStorage('nosy', ''),
            cgi.MiniFieldStorage('title', '')
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 412)
        results = self.server.get_element('issue', issue_id, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['title'], 'foo')
        self.assertEqual(len(results['attributes']['nosy']), 2)
        self.assertEqual(results['attributes']['nosy'], ['1', '2'])

        # remove the nosy list and the title
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.issue.getnode(issue_id))
        form.list = [
            cgi.MiniFieldStorage('op', 'remove'),
            cgi.MiniFieldStorage('nosy', ''),
            cgi.MiniFieldStorage('title', ''),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(results['attributes']['title'], None)
        self.assertEqual(len(results['attributes']['nosy']), 0)
        self.assertEqual(results['attributes']['nosy'], [])

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
            cgi.MiniFieldStorage('op', 'action'),
            cgi.MiniFieldStorage('action_name', 'retire')
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 412)
        self.assertFalse(self.db.issue.is_retired(issue_id))

        # execute action retire
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.issue.getnode(issue_id))
        form.list = [
            cgi.MiniFieldStorage('op', 'action'),
            cgi.MiniFieldStorage('action_name', 'retire'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        self.assertTrue(self.db.issue.is_retired(issue_id))

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
            cgi.MiniFieldStorage('op', 'remove'),
            cgi.MiniFieldStorage('nosy', '1, 2'),
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 412)
        results = self.server.get_element('issue', issue_id, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 3)
        self.assertEqual(results['attributes']['nosy'], ['1', '2', '3'])

        # remove the nosy list and the title
        form = cgi.FieldStorage()
        etag = calculate_etag(self.db.issue.getnode(issue_id))
        form.list = [
            cgi.MiniFieldStorage('op', 'remove'),
            cgi.MiniFieldStorage('nosy', '1, 2'),
            cgi.MiniFieldStorage('@etag', etag)
        ]
        results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(self.dummy_client.response_code, 200)

        # verify the result
        results = self.server.get_element('issue', issue_id, self.empty_form)
        results = results['data']
        self.assertEqual(self.dummy_client.response_code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 1)
        self.assertEqual(results['attributes']['nosy'], ['3'])


def get_obj(path, id):
    return {
        'id': id,
        'link': path + id
    }

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)
