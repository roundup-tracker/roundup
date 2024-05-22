import shutil, errno, pytest, json, gzip, mimetypes, os, re

from roundup import date as rdate
from roundup import i18n
from roundup import password
from roundup.anypy.strings import b2s
from roundup.cgi.wsgi_handler import RequestDispatcher
from .wsgi_liveserver import LiveServerTestCase
from . import db_test_base
from time import sleep
from .test_postgresql import skip_postgresql

from wsgiref.validate import validator

try:
    import requests
    skip_requests = lambda func, *args, **kwargs: func
except ImportError:
    from .pytest_patcher import mark_class
    skip_requests = mark_class(pytest.mark.skip(
        reason='Skipping liveserver tests: requests library not available'))

try:
    import brotli
    skip_brotli = lambda func, *args, **kwargs: func
except ImportError:
    from .pytest_patcher import mark_class
    skip_brotli = mark_class(pytest.mark.skip(
        reason='Skipping brotli tests: brotli library not available'))
    brotli = None

try:
    import zstd
    skip_zstd = lambda func, *args, **kwargs: func
except ImportError:
    from .pytest_patcher import mark_class
    skip_zstd = mark_class(pytest.mark.skip(
        reason='Skipping zstd tests: zstd library not available'))

import sys

_py3 = sys.version_info[0] > 2

@skip_requests
class WsgiSetup(LiveServerTestCase):
    # have chicken and egg issue here. Need to encode the base_url
    # in the config file but we don't know it until after
    # the server is started and has read the config.ini.
    # so only allow one port number
    port_range = (9001, 9001)  # default is (8080, 8090)

    dirname = '_test_instance'
    backend = 'anydbm'

    js_mime_type = mimetypes.guess_type("utils.js")[0]

    @classmethod
    def setup_class(cls):
        '''All tests in this class use the same roundup instance.
           This instance persists across all tests.
           Create the tracker dir here so that it is ready for the
           create_app() method to be called.
        '''
        # tests in this class.
        # set up and open a tracker
        cls.instance = db_test_base.setupTracker(cls.dirname, cls.backend)

        # open the database
        cls.db = cls.instance.open('admin')

        # add a user without edit access for status.
        cls.db.user.create(username="fred", roles='User',
            password=password.Password('sekrit'), address='fred@example.com')

        # set the url the test instance will run at.
        cls.db.config['TRACKER_WEB'] = "http://localhost:9001/"
        # set up mailhost so errors get reported to debuging capture file
        cls.db.config.MAILHOST = "localhost"
        cls.db.config.MAIL_HOST = "localhost"
        cls.db.config.MAIL_DEBUG = "../_test_tracker_mail.log"

        # added to enable csrf forgeries/CORS to be tested
        cls.db.config.WEB_CSRF_ENFORCE_HEADER_ORIGIN = "required"
        cls.db.config.WEB_ALLOWED_API_ORIGINS = "https://client.com"
        cls.db.config['WEB_CSRF_ENFORCE_HEADER_X-REQUESTED-WITH'] = "required"

        # disable web login rate limiting. The fast rate of tests
        # causes them to trip the rate limit and fail.
        cls.db.config.WEB_LOGIN_ATTEMPTS_MIN = 0
        
        # enable static precompressed files
        cls.db.config.WEB_USE_PRECOMPRESSED_FILES = 1

        cls.db.config.save()

        # add an issue to allow testing retrieval.
        # also used for text searching.
        result = cls.db.issue.create(title="foo bar RESULT")

        # add a message to allow retrieval
        result = cls.db.msg.create(author = "1",
                                   content = "a message foo bar RESULT",
                                   date=rdate.Date(),
                                   messageid="test-msg-id")

        # add a query using @current_user
        result = cls.db.query.create(
            klass="issue",
            name="I created",
            private_for=None,
            url=("@columns=title,id,activity,status,assignedto&"
                 "@sort=activity&@group=priority&@filter=creator&"
                 "@pagesize=50&@startwith=0&creator=%40current_user")
            )

        cls.db.commit()
        cls.db.close()
        
        # Force locale config to find locales in checkout not in
        # installed directories
        cls.backup_domain = i18n.DOMAIN
        cls.backup_locale_dirs = i18n.LOCALE_DIRS
        i18n.LOCALE_DIRS = ['locale']
        i18n.DOMAIN = ''

    @classmethod
    def teardown_class(cls):
        '''Close the database and delete the tracker directory
           now that the app should be exiting.
        '''
        if cls.db:
            cls.db.close()
        try:
            shutil.rmtree(cls.dirname)
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise
        i18n.LOCALE_DIRS = cls.backup_locale_dirs
        i18n.DOMAIN = cls.backup_domain

    def create_app(self):
        '''The wsgi app to start - no feature_flags set.
           Post 2.3.0 this enables the cache_tracker feature.
        '''

        if _py3:
            return validator(RequestDispatcher(self.dirname))
        else:
            # wsgiref/validator.py InputWrapper::readline is broke and
            # doesn't support the max bytes to read argument.
            return RequestDispatcher(self.dirname)


@skip_requests
class BaseTestCases(WsgiSetup):
    """Class with all tests to run against wsgi server. Is reused when
       wsgi server is started with various feature flags
    """

    def create_login_session(self, username="admin", password="sekrit",
                             return_response=True, expect_login_ok=True):
        # Set up session to manage cookies <insert blue monster here>
        session = requests.Session()
        session.headers.update({'Origin': 'http://localhost:9001'})

        # login using form to get cookie
        login = {"__login_name": username, '__login_password': password,
                 "@action": "login"}
        response = session.post(self.url_base()+'/', data=login)

        if expect_login_ok:
            # verify we have a cookie
            self.assertIn('roundup_session_Roundupissuetracker',
                          session.cookies)

        if not return_response:
            return session
        return session, response


    def test_query(self):
        current_user_query = (
            "@columns=title,id,activity,status,assignedto&"
            "@sort=activity&@group=priority&@filter=creator&"
            "@pagesize=50&@startwith=0&creator=%40current_user&"
            "@dispname=Test1")

        session, _response = self.create_login_session()
        f = session.get(self.url_base()+'/issue?' + current_user_query)

        # verify the query has run by looking for the query name
        self.assertIn('List of issues\n   - Test1', f.text)
        # find title of issue 1
        self.assertIn('foo bar RESULT', f.text)
        # match footer "1..1 out of 1" if issue is found
        self.assertIn('out of', f.text)
        # logout
        f = session.get(self.url_base()+'/?@action=logout')


        # set up for another user
        session, _response = self.create_login_session(username="fred")
        f = session.get(self.url_base()+'/issue?' + current_user_query)

        # verify the query has run
        self.assertIn('List of issues\n   - Test1', f.text)
        # We should have no rows, so verify the static part
        # of the footer is missing.
        self.assertNotIn('out of', f.text)

    def test_start_page(self):
        """ simple test that verifies that the server can serve a start page.
        """
        f = requests.get(self.url_base())
        self.assertEqual(f.status_code, 200)
        self.assertTrue(b'Roundup' in f.content)
        self.assertTrue(b'Creator' in f.content)

    def test_start_in_german(self):
        """ simple test that verifies that the server can serve a start page
            and translate text to german. Use page title and remeber login
            checkbox label as translation test points..

            use:
               url parameter @language
               cookie set by param
               set @language to none and verify language cookie is unset
        """

        # test url parameter
        f = requests.get(self.url_base() + "?@language=de")
        self.assertEqual(f.status_code, 200)
        print(f.content)
        self.assertTrue(b'Roundup' in f.content)
        self.assertTrue(b'Aufgabenliste' in f.content)
        self.assertTrue(b'dauerhaft anmelden?' in f.content)

        # test language cookie - should still be german
        bluemonster = f.cookies
        f = requests.get(self.url_base(), cookies=bluemonster)
        self.assertEqual(f.status_code, 200)
        print(f.content)
        self.assertTrue(b'Roundup' in f.content)
        self.assertTrue(b'Aufgabenliste' in f.content)
        self.assertTrue(b'dauerhaft anmelden?' in f.content)

        # unset language cookie, should be english
        f = requests.get(self.url_base() + "?@language=none")
        self.assertEqual(f.status_code, 200)
        print(f.content)
        self.assertTrue(b'Roundup' in f.content)
        self.assertFalse(b'Aufgabenliste' in f.content)
        self.assertFalse(b'dauerhaft anmelden?' in f.content)
        with self.assertRaises(KeyError):
            l = f.cookies['roundup_language']

        # check with Accept-Language header
        alh = {"Accept-Language":
               "fr;q=0.2, en;q=0.8, de;q=0.9, *;q=0.5"}
        f = requests.get(self.url_base(), headers=alh)
        self.assertEqual(f.status_code, 200)
        print(f.content)
        self.assertTrue(b'Roundup' in f.content)
        self.assertTrue(b'Aufgabenliste' in f.content)
        self.assertTrue(b'dauerhaft anmelden?' in f.content)

    def test_byte_Ranges(self):
        """ Roundup only handles one simple two number range, or
            a single number to start from:
            Range: 10-20
            Range: 10-

            The following is not supported.
            Range: 10-20, 25-30
            Range: -10

            Also If-Range only supports strong etags not dates or weak etags.

        """

        # get whole file uncompressed. Extract content length and etag
        # for future use
        f = requests.get(self.url_base() + "/@@file/style.css",
                         headers = {"Accept-Encoding": "identity"})
        # store etag for condition range testing
        etag = f.headers['etag']
        expected_length = f.headers['content-length']

        # get first 11 bytes unconditionally (0 index really??)
        hdrs = {"Range": "bytes=0-10"}
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 206)
        self.assertEqual(f.content, b"/* main pag")
        # compression disabled for length < 100, so we can use 11 here
        self.assertEqual(f.headers['content-length'], '11')
        self.assertEqual(f.headers['content-range'],
                         "bytes 0-10/%s"%expected_length)

        # get bytes 11-21 unconditionally (0 index really??)
        hdrs = {"Range": "bytes=10-20"}
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 206)
        self.assertEqual(f.content, b"ge styles *")
        # compression disabled for length < 100, so we can use 11 here
        self.assertEqual(f.headers['content-length'], '11')
        self.assertEqual(f.headers['content-range'],
                         "bytes 10-20/%s"%expected_length)

        # get all bytes starting from 11
        hdrs = {"Range": "bytes=11-"}
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 206)
        self.assertEqual(f.headers['content-range'],
                         "bytes 11-%s/%s"%(int(expected_length) - 1,
                                           expected_length))
        self.assertIn(b"SHA:", f.content)  # detect sha sum at end of file

        # conditional request 11 bytes since etag matches 206 code
        hdrs = {"Range": "bytes=0-10"}
        hdrs['If-Range'] = etag
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 206)
        self.assertEqual(f.content, b"/* main pag")
        # compression disabled for length < 100, so we can use 11 here
        self.assertEqual(f.headers['content-length'], '11')
        self.assertEqual(f.headers['content-range'],
                         "bytes 0-10/%s"%expected_length)

        # conditional request returns all bytes as etag isn't correct 200 code
        hdrs['If-Range'] = etag[2:]  # bad tag
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        # not checking content length since it could be compressed
        self.assertNotIn('content-range', f.headers, 'content-range should not be present')

        # range is too large, but etag is bad also, return whole file 200 code
        hdrs['Range'] = "0-99999" # too large
        hdrs['If-Range'] = '"' + etag[2:]  # start bad tag with "
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        # note f.content has content-encoding (compression) undone.
        self.assertEqual(len(f.content), int(expected_length))
        self.assertNotIn('content-range', f.headers, 'content-range should not be present')

        # range is too large, but etag is specified so return whole file
        # 200 code
        hdrs['Range'] = "bytes=0-99999" # too large
        hdrs['If-Range'] = etag  # any tag works
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        # not checking content length since it could be compressed
        self.assertNotIn('content-range', f.headers, 'content-range should not be present')

        # range too large, not if-range so error code 416
        hdrs['Range'] = "bytes=0-99999" # too large
        del(hdrs['If-Range'])
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 416)
        self.assertEqual(f.headers['content-range'],
                         "bytes */%s"%expected_length)

        # invalid range multiple ranges
        hdrs['Range'] = "bytes=0-10, 20-45"
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        self.assertNotIn('content-range', f.headers,
                         'content-range should not be present')
        self.assertIn(b"SHA:", f.content)  # detect sha sum at end of file

        # invalid range is single number not number followed by -
        hdrs['Range'] = "bytes=1"
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        self.assertNotIn('content-range', f.headers,
                         'content-range should not be present')
        self.assertIn(b"SHA:", f.content)  # detect sha sum at end of file

        # range is invalid first number not a number
        hdrs['Range'] = "bytes=boom-99" # bad first value
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        self.assertNotIn('content-range', f.headers,
                         'content-range should not be present')
        self.assertIn(b"SHA:", f.content)  # detect sha sum at end of file

        # range is invalid last number not a number
        hdrs['Range'] = "bytes=1-boom" # bad last value
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        self.assertNotIn('content-range', f.headers,
                         'content-range should not be present')
        self.assertIn(b"SHA:", f.content)  # detect sha sum at end of file

        # range is invalid first position empty
        hdrs['Range'] = "bytes=-11" # missing first value
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        self.assertNotIn('content-range', f.headers,
                         'content-range should not be present')
        self.assertIn(b"SHA:", f.content)  # detect sha sum at end of file

        # range is invalid #2 < #1
        hdrs['Range'] = "bytes=11-1" # inverted range
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        self.assertNotIn('content-range', f.headers,
                         'content-range should not be present')
        self.assertIn(b"SHA:", f.content)  # detect sha sum at end of file

        # range is invalid negative first number
        hdrs['Range'] = "bytes=-1-11" # negative first number
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        self.assertNotIn('content-range', f.headers,
                         'content-range should not be present')
        self.assertIn(b"SHA:", f.content)  # detect sha sum at end of file

        # range is invalid negative second number
        hdrs['Range'] = "bytes=1--11" # negative second number
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        self.assertNotIn('content-range', f.headers,
                         'content-range should not be present')
        self.assertIn(b"SHA:", f.content)  # detect sha sum at end of file

        # range is unsupported units
        hdrs['Range'] = "badunits=1-11"
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        self.assertNotIn('content-range', f.headers,
                         'content-range should not be present')
        self.assertIn(b"SHA:", f.content)  # detect sha sum at end of file


        # valid range, invalid file
        hdrs['Range'] = "bytes=0-11"
        print(hdrs)
        f = requests.get(self.url_base() + "/@@file/style_nope.css",
                         headers=hdrs)
        self.assertEqual(f.status_code, 404)
        self.assertNotIn('content-range', f.headers,
                         'content-range should not be present')

    def test_rest_preflight_collection(self):
        # no auth for rest csrf preflight
        f = requests.options(self.url_base() + '/rest/data/user',
                             headers = {'content-type': "",
                             'x-requested-with': "rest",
                             'Access-Control-Request-Headers':
                                 "x-requested-with",
                             'Access-Control-Request-Method': "PUT",
                             'Origin': "https://client.com"})
        print(f.status_code)
        print(f.headers)
        print(f.content)

        self.assertEqual(f.status_code, 204)

        expected = { 'Access-Control-Allow-Origin': 'https://client.com',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST',
                     'Access-Control-Allow-Methods': 'OPTIONS, GET, POST',
                     'Access-Control-Allow-Credentials': 'true',
        }

        # use dict comprehension to filter headers to the ones we want to check
        self.assertEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                         expected)

        # use invalid Origin
        f = requests.options(self.url_base() + '/rest/data/user',
                             headers = {'content-type': "application/json",
                             'x-requested-with': "rest",
                             'Access-Control-Request-Headers':
                                 "x-requested-with",
                             'Access-Control-Request-Method': "PUT",
                             'Origin': "ZZZ"})

        self.assertEqual(f.status_code, 400)

        expected = '{ "error": { "status": 400, "msg": "Client is not ' \
                   'allowed to use Rest Interface." } }'
        self.assertEqual(b2s(f.content), expected)

        # Test when Origin is not sent.
        f = requests.options(self.url_base() + '/rest/data/user',
                             headers = {'content-type': "application/json",
                             'x-requested-with': "rest",
                             'Access-Control-Request-Headers':
                                 "x-requested-with",
                             'Access-Control-Request-Method': "PUT",})

        self.assertEqual(f.status_code, 400)

        expected = ('{ "error": { "status": 400, "msg": "Required'
                    ' Header Missing" } }')
        self.assertEqual(b2s(f.content), expected)


    def test_rest_invalid_method_collection(self):
        # use basic auth for rest endpoint
        f = requests.put(self.url_base() + '/rest/data/user',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'X-Requested-With': "rest",
                                        'Origin': "https://client.com"})
        print(f.status_code)
        print(f.headers)
        print(f.content)

        self.assertEqual(f.status_code, 405)
        expected = { 'Access-Control-Allow-Origin': 'https://client.com',
                     'Access-Control-Allow-Credentials': 'true',
                     'Allow': 'DELETE, GET, OPTIONS, POST',
        }

        print(f.headers)
        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

        content = json.loads(f.content)

        exp_content = "Method PUT not allowed. Allowed: DELETE, GET, OPTIONS, POST"
        self.assertEqual(exp_content, content['error']['msg'])

    def test_http_options(self):
        """ options returns an unimplemented error for this case."""
        
        # do not send content-type header for options
        f = requests.options(self.url_base() + '/',
                             headers = {'content-type': ""})
        # options is not implemented for the non-rest interface.
        self.assertEqual(f.status_code, 501)

    def test_rest_endpoint_root_options(self):
        # use basic auth for rest endpoint
        f = requests.options(self.url_base() + '/rest',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Origin': "http://localhost:9001",
                             })
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected = { 'Access-Control-Allow-Origin': 'http://localhost:9001',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET',
                     'Access-Control-Allow-Credentials': 'true',
                     'Access-Control-Allow-Methods': 'OPTIONS, GET',
                     'Access-Control-Allow-Credentials': 'true',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

    def test_rest_endpoint_data_options(self):
        # use basic auth for rest endpoint
        f = requests.options(self.url_base() + '/rest/data',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Origin': "http://localhost:9001",
                             })
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected = { 'Access-Control-Allow-Origin': 'http://localhost:9001',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET',
                     'Access-Control-Allow-Methods': 'OPTIONS, GET',
                     'Access-Control-Allow-Credentials': 'true',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

    def test_rest_endpoint_collection_options(self):
        # use basic auth for rest endpoint
        f = requests.options(self.url_base() + '/rest/data/user',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Origin': "http://localhost:9001",
                             })
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected = { 'Access-Control-Allow-Origin': 'http://localhost:9001',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST',
                     'Access-Control-Allow-Methods': 'OPTIONS, GET, POST',
                     'Access-Control-Allow-Credentials': 'true',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)


    def test_rest_endpoint_item_options(self):

        f = requests.options(self.url_base() + '/rest/data/user/1',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Origin': "http://localhost:9001",
                             })
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected = { 'Access-Control-Allow-Origin': 'http://localhost:9001',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'OPTIONS, GET, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Credentials': 'true',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

    def test_rest_endpoint_attribute_options(self):
        # use basic auth for rest endpoint
        f = requests.options(self.url_base() + '/rest/data/user/1/username',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Origin': "http://localhost:9001",
                             })
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected = { 'Access-Control-Allow-Origin': 'http://localhost:9001',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'OPTIONS, GET, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Credentials': 'true',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

        ## test a read only property.

        f = requests.options(self.url_base() + '/rest/data/user/1/creator',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Origin': "http://localhost:9001",
                             })
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected1 = dict(expected)
        expected1['Allow'] = 'OPTIONS, GET'
        expected1['Access-Control-Allow-Methods'] = 'OPTIONS, GET'

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected1)

        ## test a property that doesn't exist
        f = requests.options(self.url_base() + '/rest/data/user/1/zot',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Origin': "http://localhost:9001",})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 404)

    def test_rest_endpoint_user_roles(self):
        # use basic auth for rest endpoint
        f = requests.get(self.url_base() + '/rest/data/user/roles',
                         auth=('admin', 'sekrit'),
                         headers = {'content-type': "",
                                    'Origin': "http://localhost:9001",
                         })
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Access-Control-Expose-Headers': 'X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, X-RateLimit-Limit-Period, Retry-After, Sunset, Allow',
                     'Access-Control-Allow-Credentials': 'true',
                     'Allow': 'GET',
        }
        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

        content = json.loads(f.content)

        self.assertEqual(3, len(json.loads(f.content)['data']['collection']))


    def test_ims(self):
        ''' retreive the user_utils.js file with old and new
            if-modified-since timestamps.
        '''
        from datetime import datetime

        f = requests.get(self.url_base() + '/@@file/user_utils.js',
                         headers = { 'Accept-Encoding': 'gzip, foo',
                                     'If-Modified-Since': 'Sun, 13 Jul 1986 01:20:00',
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': self.js_mime_type,
                     'Content-Encoding': 'gzip',
                     'Vary': 'Accept-Encoding',
        }

        # use dict comprehension to remove fields like date,
        # etag etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

        # now use today's date
        a_few_seconds_ago = datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT') 
        f = requests.get(self.url_base() + '/@@file/user_utils.js',
                         headers = { 'Accept-Encoding': 'gzip, foo',
                                     'If-Modified-Since': a_few_seconds_ago,
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 304)
        expected = { 'Vary': 'Accept-Encoding',
                     'Content-Length': '0',
        }

        # use dict comprehension to remove fields like date, etag
        #  etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)


    def test_load_issue1(self):
        for tail in [
                '/issue1',      # normal url
                '/issue00001',  # leading 0's should be stripped from id
                '/issue1>'      # surprise this works too, should it??
        ]:
            f = requests.get(self.url_base() + tail,
                             headers = { 'Accept-Encoding': 'gzip',
                                         'Accept': '*/*'})

            self.assertIn(b'foo bar RESULT', f.content)
            self.assertEqual(f.status_code, 200)

    def test_load_msg1(self):
        # leading 0's should be stripped from id
        f = requests.get(self.url_base() + '/msg0001',
                         headers = { 'Accept-Encoding': 'gzip',
                                     'Accept': '*/*'})

        self.assertIn(b'foo bar RESULT', f.content)
        self.assertEqual(f.status_code, 200)

    def test_bad_path(self):
        f = requests.get(self.url_base() + '/_bad>',
                         headers = { 'Accept-Encoding': 'gzip, foo',
                                     'Accept': '*/*'})

        # test that returned text is encoded.
        self.assertEqual(f.content, b'Not found: _bad&gt;')
        self.assertEqual(f.status_code, 404)

    def test_compression_gzipfile(self):
        '''Get the compressed dummy file'''

        # create a user_utils.js.gz file to test pre-compressed
        # file serving code. Has custom contents to verify
        # that I get the compressed one.
        gzfile = "%s/html/user_utils.js.gzip"%self.dirname
        test_text= b"Custom text for user_utils.js\n"

        with gzip.open(gzfile, 'wb') as f:
            bytes_written = f.write(test_text)

        self.assertEqual(bytes_written, 30)

        # test file x-fer
        f = requests.get(self.url_base() + '/@@file/user_utils.js',
                         headers = { 'Accept-Encoding': 'gzip, foo',
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': self.js_mime_type,
                     'Content-Encoding': 'gzip',
                     'Vary': 'Accept-Encoding',
                     'Content-Length': '69',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)


        # check content - verify it's the .gz file not the real file.
        self.assertEqual(f.content, test_text)

        '''# verify that a different encoding request returns on the fly

        # test file x-fer using br, so we get runtime compression
        f = requests.get(self.url_base() + '/@@file/user_utils.js',
                         headers = { 'Accept-Encoding': 'br, foo',
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': self.js_mime_type,
                     'Content-Encoding': 'br',
                     'Vary': 'Accept-Encoding',
                     'Content-Length': '960',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)

        try:
           from urllib3.response import BrotliDecoder
           # requests has decoded br to text for me
           data = f.content
        except ImportError:
            # I need to decode
            data = brotli.decompress(f.content)

        self.assertEqual(b2s(data)[0:25], '// User Editing Utilities')
        '''

        # re-request file, but now make .gzip out of date. So we get the
        # real file compressed on the fly, not our test file.
        os.utime(gzfile, (0,0)) # use 1970/01/01 or os base time

        f = requests.get(self.url_base() + '/@@file/user_utils.js',
                         headers = { 'Accept-Encoding': 'gzip, foo',
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': self.js_mime_type,
                     'Content-Encoding': 'gzip',
                     'Vary': 'Accept-Encoding',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)


        # check content - verify it's the real file, not crafted .gz.
        self.assertEqual(b2s(f.content)[0:25], '// User Editing Utilities')

        # cleanup
        os.remove(gzfile)

    def test_compression_none_etag(self):
        # use basic auth for rest endpoint
        f = requests.get(self.url_base() + '/rest/data/user/1/username',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Accept-Encoding': "",
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Credentials': 'true',
                     'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH',
        }

        content_str = '''{ "data": {
                        "id": "1",
                        "link": "http://localhost:9001/rest/data/user/1/username",
                        "data": "admin"
                    }
        }'''
        content = json.loads(content_str)


        if (type("") == type(f.content)):
            json_dict = json.loads(f.content)
        else:
            json_dict = json.loads(b2s(f.content))

        # etag wil not match, creation date different
        del(json_dict['data']['@etag']) 

        # type is "class 'str'" under py3, "type 'str'" py2
        # just skip comparing it.
        del(json_dict['data']['type']) 

        self.assertDictEqual(json_dict, content)

        # verify that ETag header has no - delimiter
        print(f.headers['ETag'])
        with self.assertRaises(ValueError):
            f.headers['ETag'].index('-')

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)


    def test_compression_gzip(self, method='gzip'):
        if method == 'gzip':
            decompressor = None
        elif method == 'br':
            decompressor = brotli.decompress
        elif method == 'zstd':
            decompressor = zstd.decompress
            
        # use basic auth for rest endpoint
        f = requests.get(self.url_base() + '/rest/data/user/1/username',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Accept-Encoding': '%s, foo'%method,
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Credentials': 'true',
                     'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Content-Encoding': method,
                     'Vary': 'Origin, Accept-Encoding',
        }

        content_str = '''{ "data": {
                        "id": "1",
                        "link": "http://localhost:9001/rest/data/user/1/username",
                        "data": "admin"
                    }
        }'''
        content = json.loads(content_str)

        print(f.content)
        print(type(f.content))

        try:
            if (type("") == type(f.content)):
                json_dict = json.loads(f.content)
            else:
                json_dict = json.loads(b2s(f.content))
        except (ValueError, UnicodeDecodeError):
            # Handle error from trying to load compressed data as only
            # gzip gets decompressed automatically
            # ValueError - raised by loads on compressed content python2
            # UnicodeDecodeError - raised by loads on compressed content
            #    python3
            json_dict = json.loads(b2s(decompressor(f.content)))

        # etag will not match, creation date different
        del(json_dict['data']['@etag']) 

        # type is "class 'str'" under py3, "type 'str'" py2
        # just skip comparing it.
        del(json_dict['data']['type']) 

        self.assertDictEqual(json_dict, content)

        # verify that ETag header ends with -<method>
        try:
            self.assertRegex(f.headers['ETag'], r'^"[0-9a-f]{32}-%s"$'%method)
        except AttributeError:
            # python2 no assertRegex so try substring match
            self.assertEqual(33, f.headers['ETag'].rindex('-' + method))

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)


        # use basic auth for rest endpoint, error case, bad attribute
        f = requests.get(self.url_base() + '/rest/data/user/1/foo',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Accept-Encoding': '%s, foo'%method,
                                        'Accept': '*/*',
                                        'Origin': 'https://client.com'})
        print(f.status_code)
        print(f.headers)

        # NOTE: not compressed payload too small
        self.assertEqual(f.status_code, 400)
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Credentials': 'true',
                     'Access-Control-Allow-Origin': 'https://client.com',
                     'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Vary': 'Origin'
        }

        content = { "error":
                    {
                        "status": 400,
                        "msg": "Invalid attribute foo"
                    }
        }

        json_dict = json.loads(b2s(f.content))
        self.assertDictEqual(json_dict, content)

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

        # test file x-fer
        f = requests.get(self.url_base() + '/@@file/user_utils.js',
                         headers = { 'Accept-Encoding': '%s, foo'%method,
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': self.js_mime_type,
                     'Content-Encoding': method,
                     'Vary': 'Accept-Encoding',
        }

        # compare to byte string as f.content may be compressed.
        # so running b2s on it will throw a UnicodeError
        if f.content[0:25] == b'// User Editing Utilities':
            # no need to decompress, urlib3.response did it for gzip and br
           data = f.content
        else:
            # I need to decode
            data = decompressor(f.content)

        # check first few bytes.
        self.assertEqual(b2s(data)[0:25], '// User Editing Utilities')

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)

        # test file x-fer
        f = requests.get(self.url_base() + '/user1',
                         headers = { 'Accept-Encoding': '%s, foo'%method,
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'text/html; charset=utf-8',
                     'Content-Encoding': method,
                     'Vary': 'Accept-Encoding',
        }

        if f.content[0:25] ==  b'<!-- dollarId: user.item,':
            # no need to decompress, urlib3.response did it for gzip and br
           data = f.content
        else:
            # I need to decode
            data = decompressor(f.content)

        # check first few bytes.
        self.assertEqual(b2s(data[0:25]), '<!-- dollarId: user.item,')

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)

    @skip_brotli
    def test_compression_br(self):
        self.test_compression_gzip(method="br")

    @skip_zstd
    def test_compression_zstd(self):
        self.test_compression_gzip(method="zstd")

    def test_cache_control_css(self):
        f = requests.get(self.url_base() + '/@@file/style.css',
                             headers = {'content-type': "",
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        self.assertEqual(f.headers['Cache-Control'], 'public, max-age=4838400')

    def test_cache_control_js(self):
        f = requests.get(self.url_base() + '/@@file/help_controls.js',
                             headers = {'content-type': "",
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        self.assertEqual(f.headers['Cache-Control'], 'public, max-age=1209600')

    def test_missing_session_key(self):
        '''Test case where we have an outdated session cookie. Make
           sure cookie is removed.
        '''

        session, f = self.create_login_session()

        # verify cookie is present and we are logged in
        self.assertIn('<b>Hello, admin</b>', f.text)
        self.assertIn('roundup_session_Roundupissuetracker',
                         session.cookies)

        f = session.get(self.url_base()+'/')
        self.assertIn('<b>Hello, admin</b>', f.text)

        for cookie in session.cookies:
            if cookie.name == 'roundup_session_Roundupissuetracker':
                cookie.value = 'bad_cookie_no_chocolate'
                break

        f = session.get(self.url_base()+'/')

        self.assertNotIn('<b>Hello, admin</b>', f.text)
        self.assertNotIn('roundup_session_Roundupissuetracker', session.cookies)

    def test_login_fail_then_succeed(self):

        session, f = self.create_login_session(password="bad_sekrit",
                                               expect_login_ok=False)

        # verify error message and no hello message in sidebar.
        self.assertIn('class="error-message">Invalid login <br/ >', f.text)
        self.assertNotIn('<b>Hello, admin</b>', f.text)

        session, f = self.create_login_session(return_response=True)
        self.assertIn('<b>Hello, admin</b>', f.text)

    def test__generic_item_template_editok(self, user="admin"):
        """Load /status7 object. Admin has edit rights so should see
           a submit button. fred doesn't have edit rights
           so should not have a submit button.
        """
        session, f = self.create_login_session(username=user)

        # look for change in text in sidebar post login
        self.assertIn('Hello, %s'%user, f.text)
        f = session.get(self.url_base()+'/status7')
        print(f.content)

        # status7's name is done-cbb
        self.assertIn(b'done-cbb', f.content)

        if user == 'admin':
            self.assertIn(b'<input name="submit_button" type="submit" value="Submit Changes">', f.content)
        else:
            self.assertNotIn(b'<input name="submit_button" type="submit" value="Submit Changes">', f.content)

        # logout
        f = session.get(self.url_base()+'/?@action=logout')
        self.assertIn(b"Remember me?", f.content)

    @pytest.mark.xfail
    def test__generic_item_template_editbad(self, user="fred"):
        self.test__generic_item_template_editok(user=user)

    def test_new_issue_with_file_upload(self):
        session, f = self.create_login_session()

        # look for change in text in sidebar post login
        self.assertIn('Hello, admin', f.text)

        # create a new issue and upload a file
        file_content = 'this is a test file\n'
        file = {"@file": ('test1.txt', file_content, "text/plain") }
        issue = {"title": "my title", "priority": "1", "@action": "new"}
        f = session.post(self.url_base()+'/issue?@template=item', data=issue, files=file)

        # use redirected url to determine which issue and file were created.
        m = re.search(r'[0-9]/issue(?P<issue>[0-9]+)\?@ok_message.*file%20(?P<file>[0-9]+)%20', f.url)

        # verify message in redirected url: file 1 created\nissue 1 created
        # warning may fail if another test loads tracker with files.
        # Escape % signs in string by doubling them. This verifies the
        # search is working correctly.
        # use groupdict for python2.
        self.assertEqual('http://localhost:9001/issue%(issue)s?@ok_message=file%%20%(file)s%%20created%%0Aissue%%20%(issue)s%%20created&@template=item'%m.groupdict(), f.url)

        # we have an issue display, verify filename is listed there
        # seach for unique filename given to it.
        self.assertIn("test1.txt", f.text)

        # download file and verify content
        f = session.get(self.url_base()+'/file%(file)s/text1.txt'%m.groupdict())
        self.assertEqual(f.text, file_content)
        self.assertEqual(f.headers["X-Content-Type-Options"], "nosniff")
        print(f.text)

    def test_new_file_via_rest(self):

        session = requests.Session()
        session.auth = ('admin', 'sekrit')

        url = self.url_base() + '/rest/data/'
        fname   = 'a-bigger-testfile'
        d = dict(name = fname, type='application/octet-stream')
        c = dict (content = r'xyzzy')
        r = session.post(url + 'file', files = c, data = d,
                          headers = {'x-requested-with': "rest",
                                     'Origin': "http://localhost:9001"}
        )

        # was a 500 before fix for issue2551178
        self.assertEqual(r.status_code, 201)
        # just compare the path leave off the number
        self.assertIn('http://localhost:9001/rest/data/file/',
                      r.headers["location"])
        json_dict = json.loads(r.text)
        self.assertEqual(json_dict["data"]["link"], r.headers["location"])

        # download file and verify content
        r = session.get(r.headers["location"] +'/content',
                          headers = {'x-requested-with': "rest",
                                     'Origin': "http://localhost:9001"}
)
        json_dict = json.loads(r.text)
        self.assertEqual(json_dict['data']['data'], c["content"])
        print(r.text)

        # Upload a file via rest interface - no auth 
        session.auth = None
        r = session.post(url + 'file', files = c, data = d,
                          headers = {'x-requested-with': "rest",
                                     'Origin': "http://localhost:9001"}
        )
        self.assertEqual(r.status_code, 403)

        # get session variable from web form login
        #   and use it to upload file
        session, f = self.create_login_session()
        # look for change in text in sidebar post login
        self.assertIn('Hello, admin', f.text)

        r = session.post(url + 'file', files = c, data = d,
                          headers = {'x-requested-with': "rest",
                                     'Origin': "http://localhost:9001"}
        )
        self.assertEqual(r.status_code, 201)
        print(r.status_code)
        
    def test_fts(self):
        f = requests.get(self.url_base() + "?@search_text=RESULT")
        self.assertIn("foo bar", f.text)

@skip_requests
class TestFeatureFlagCacheTrackerOff(BaseTestCases, WsgiSetup):
    """Class to run all test in BaseTestCases with the cache_tracker
       feature flag disabled when starting the wsgi server
    """
    def create_app(self):
        '''The wsgi app to start with feature flag disabled'''
        ff = { "cache_tracker": False }
        if _py3:
            return validator(RequestDispatcher(self.dirname, feature_flags=ff))
        else:
            # wsgiref/validator.py InputWrapper::readline is broke and
            # doesn't support the max bytes to read argument.
            return RequestDispatcher(self.dirname, feature_flags=ff)

@skip_postgresql
@skip_requests
class TestPostgresWsgiServer(BaseTestCases, WsgiSetup):
    """Class to run all test in BaseTestCases with the cache_tracker
       feature enabled when starting the wsgi server
    """

    backend = 'postgresql'

    @classmethod
    def setup_class(cls):
        '''All tests in this class use the same roundup instance.
           This instance persists across all tests.
           Create the tracker dir here so that it is ready for the
           create_app() method to be called.

           cribbed from WsgiSetup::setup_class
        '''

        # tests in this class.
        # set up and open a tracker
        cls.instance = db_test_base.setupTracker(cls.dirname, cls.backend)

        # open the database
        cls.db = cls.instance.open('admin')

        # add a user without edit access for status.
        cls.db.user.create(username="fred", roles='User',
            password=password.Password('sekrit'), address='fred@example.com')

        # set the url the test instance will run at.
        cls.db.config['TRACKER_WEB'] = "http://localhost:9001/"
        # set up mailhost so errors get reported to debuging capture file
        cls.db.config.MAILHOST = "localhost"
        cls.db.config.MAIL_HOST = "localhost"
        cls.db.config.MAIL_DEBUG = "../_test_tracker_mail.log"

        # added to enable csrf forgeries/CORS to be tested
        cls.db.config.WEB_CSRF_ENFORCE_HEADER_ORIGIN = "required"
        cls.db.config.WEB_ALLOWED_API_ORIGINS = "https://client.com"
        cls.db.config['WEB_CSRF_ENFORCE_HEADER_X-REQUESTED-WITH'] = "required"

        cls.db.config.INDEXER = "native-fts"

        # disable web login rate limiting. The fast rate of tests
        # causes them to trip the rate limit and fail.
        cls.db.config.WEB_LOGIN_ATTEMPTS_MIN = 0
        
        # enable static precompressed files
        cls.db.config.WEB_USE_PRECOMPRESSED_FILES = 1

        cls.db.config.save()

        cls.db.commit()
        cls.db.close()

        # re-open the database to get the updated INDEXER
        cls.db = cls.instance.open('admin')

        result = cls.db.issue.create(title="foo bar RESULT")

        # add a message to allow retrieval
        result = cls.db.msg.create(author = "1",
                                   content = "a message foo bar RESULT",
                                   date=rdate.Date(),
                                   messageid="test-msg-id")

        cls.db.commit()
        cls.db.close()
        
        # Force locale config to find locales in checkout not in
        # installed directories
        cls.backup_domain = i18n.DOMAIN
        cls.backup_locale_dirs = i18n.LOCALE_DIRS
        i18n.LOCALE_DIRS = ['locale']
        i18n.DOMAIN = ''

    @classmethod
    def tearDownClass(cls):
        # cleanup
        cls.instance.backend.db_nuke(cls.db.config)

    def test_native_fts(self):
        self.assertIn("postgresql_fts", str(self.db.indexer))

        # use a ts: search as well so it only works on postgres_fts indexer
        f = requests.get(self.url_base() + "?@search_text=ts:RESULT")
        self.assertIn("foo bar RESULT", f.text)

@skip_requests
class TestApiRateLogin(WsgiSetup):
    """Class to run test in BaseTestCases with the cache_tracker
       feature flag enabled when starting the wsgi server
    """

    backend = 'sqlite'

    @classmethod
    def setup_class(cls):
        '''All tests in this class use the same roundup instance.
           This instance persists across all tests.
           Create the tracker dir here so that it is ready for the
           create_app() method to be called.

           cribbed from WsgiSetup::setup_class
        '''

        # tests in this class.
        # set up and open a tracker
        cls.instance = db_test_base.setupTracker(cls.dirname, cls.backend)

        # open the database
        cls.db = cls.instance.open('admin')

        # add a user without edit access for status.
        cls.db.user.create(username="fred", roles='User',
            password=password.Password('sekrit'), address='fred@example.com')

        # set the url the test instance will run at.
        cls.db.config['TRACKER_WEB'] = "http://localhost:9001/"
        # set up mailhost so errors get reported to debuging capture file
        cls.db.config.MAILHOST = "localhost"
        cls.db.config.MAIL_HOST = "localhost"
        cls.db.config.MAIL_DEBUG = "../_test_tracker_mail.log"

        # added to enable csrf forgeries/CORS to be tested
        cls.db.config.WEB_CSRF_ENFORCE_HEADER_ORIGIN = "required"
        cls.db.config.WEB_ALLOWED_API_ORIGINS = "https://client.com"
        cls.db.config['WEB_CSRF_ENFORCE_HEADER_X-REQUESTED-WITH'] = "required"

        # set login failure api limits
        cls.db.config.WEB_API_FAILED_LOGIN_LIMIT = 4
        cls.db.config.WEB_API_FAILED_LOGIN_INTERVAL_IN_SEC = 12

        # enable static precompressed files
        cls.db.config.WEB_USE_PRECOMPRESSED_FILES = 1

        cls.db.config.save()

        cls.db.commit()
        cls.db.close()

        # re-open the database to get the updated INDEXER
        cls.db = cls.instance.open('admin')

        result = cls.db.issue.create(title="foo bar RESULT")

        # add a message to allow retrieval
        result = cls.db.msg.create(author = "1",
                                   content = "a message foo bar RESULT",
                                   date=rdate.Date(),
                                   messageid="test-msg-id")

        cls.db.commit()
        cls.db.close()
        
        # Force locale config to find locales in checkout not in
        # installed directories
        cls.backup_domain = i18n.DOMAIN
        cls.backup_locale_dirs = i18n.LOCALE_DIRS
        i18n.LOCALE_DIRS = ['locale']
        i18n.DOMAIN = ''

    def test_rest_login_RateLimit(self):
        """login rate limit applies to api endpoints. Only failure
            logins count though. So log in 10 times in a row
            to verify that valid username/passwords aren't limited.
        """
        # On windows, using localhost in the URL with requests
        # tries an IPv6 address first. This causes a request to
        # take 2 seconds which is too slow to ever trip the rate
        # limit. So replace localhost with 127.0.0.1 that does an
        # IPv4 request only.
        url_base_numeric = self.url_base()
        url_base_numeric =  url_base_numeric.replace('localhost','127.0.0.1')

        # verify that valid logins are not counted against the limit.
        for i in range(10):
            # use basic auth for rest endpoint
        
            request_headers = {'content-type': "",
                               'Origin': "http://localhost:9001",}
            f = requests.options(url_base_numeric + '/rest/data',
                                 auth=('admin', 'sekrit'),
                                 headers=request_headers
            )
            #print(f.status_code)
            #print(f.headers)
            #print(f.text)
            
            self.assertEqual(f.status_code, 204)

        # Save time. check headers only for final response.
        headers_expected = {
            'Access-Control-Allow-Origin': request_headers['Origin'],
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
            'Allow': 'OPTIONS, GET',
            'Access-Control-Allow-Methods': 'OPTIONS, GET',
            'Access-Control-Allow-Credentials': 'true',
        }

        for header in headers_expected.keys():
            self.assertEqual(f.headers[header],
                             headers_expected[header])


        # first 3 logins should report 401 then the rest should report
        # 429
        headers_expected = {
            'Content-Type': 'text/plain'
        }

        for i in range(10):
            # use basic auth for rest endpoint
        
            f = requests.options(url_base_numeric + '/rest/data',
                                 auth=('admin', 'ekrit'),
                                 headers = {'content-type': "",
                                            'Origin': "http://localhost:9001",}
            )

            if (i < 4): # assuming limit is 4.
                for header in headers_expected.keys():
                    self.assertEqual(f.headers[header],
                                     headers_expected[header])
                self.assertEqual(f.status_code, 401)
            else:
                self.assertEqual(f.status_code, 429)

                headers_expected = { 'Content-Type': 'text/plain',
                                     'X-RateLimit-Limit': '4',
                                     'X-RateLimit-Limit-Period': '12',
                                     'X-RateLimit-Remaining': '0',
                                     'Retry-After': '3',
                                     'Access-Control-Expose-Headers':
                                     ('X-RateLimit-Limit, '
                                      'X-RateLimit-Remaining, '
                                      'X-RateLimit-Reset, '
                                      'X-RateLimit-Limit-Period, '
                                      'Retry-After'),
                                     'Content-Length': '50'}

                for header in headers_expected.keys():
                    self.assertEqual(f.headers[header],
                                     headers_expected[header])

                self.assertAlmostEqual(float(f.headers['X-RateLimit-Reset']),
                                       10.0, delta=3,
                msg="limit reset not within 3 seconds of 10")

        # test lockout this is a valid login but should be rejected
        # with 429.
        f = requests.options(url_base_numeric + '/rest/data',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Origin': "http://localhost:9001",}
        )
        self.assertEqual(f.status_code, 429)

        for header in headers_expected.keys():
            self.assertEqual(f.headers[header],
                             headers_expected[header])


        sleep(4)
        # slept long enough to get a login slot. Should work with
        # 200 return code.
        f = requests.get(url_base_numeric + '/rest/data',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Origin': "http://localhost:9001",}
        )
        self.assertEqual(f.status_code, 200)
        print(i, f.status_code)
        print(f.headers)
        print(f.text)

        headers_expected = {
            'Content-Type': 'application/json',
            'Vary': 'Origin, Accept-Encoding',
            'Access-Control-Expose-Headers':
            ( 'X-RateLimit-Limit, '
              'X-RateLimit-Remaining, '
              'X-RateLimit-Reset, '
              'X-RateLimit-Limit-Period, '
              'Retry-After, '
              'Sunset, '
              'Allow'),
            'Access-Control-Allow-Origin': 'http://localhost:9001',
            'Access-Control-Allow-Credentials': 'true',
            'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH'
        }

        for header in headers_expected.keys():
            self.assertEqual(f.headers[header],
                             headers_expected[header])

        expected_data = {
            "status": {
                "link": "http://localhost:9001/rest/data/status"
            },
            "keyword": {
                "link": "http://localhost:9001/rest/data/keyword"
            },
            "priority": {
                "link": "http://localhost:9001/rest/data/priority"
            },
            "user": {
                "link": "http://localhost:9001/rest/data/user"
            },
            "file": {
                "link": "http://localhost:9001/rest/data/file"
            },
            "msg": {
                "link": "http://localhost:9001/rest/data/msg"
            },
            "query": {
                "link": "http://localhost:9001/rest/data/query"
            },
            "issue": {
                "link": "http://localhost:9001/rest/data/issue"
            }
        }

        json_dict = json.loads(f.text)
        self.assertEqual(json_dict['data'], expected_data)
