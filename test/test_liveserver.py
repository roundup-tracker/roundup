import shutil, errno, pytest, json, gzip, os, re

from roundup import i18n
from roundup.anypy.strings import b2s
from roundup.cgi.wsgi_handler import RequestDispatcher
from .wsgi_liveserver import LiveServerTestCase
from . import db_test_base

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
class SimpleTest(LiveServerTestCase):
    # have chicken and egg issue here. Need to encode the base_url
    # in the config file but we don't know it until after
    # the server is started and has read the config.ini.
    # so only allow one port number
    port_range = (9001, 9001)  # default is (8080, 8090)

    dirname = '_test_instance'
    backend = 'anydbm'
    
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

        # set the url the test instance will run at.
        cls.db.config['TRACKER_WEB'] = "http://localhost:9001/"
        # set up mailhost so errors get reported to debuging capture file
        cls.db.config.MAILHOST = "localhost"
        cls.db.config.MAIL_HOST = "localhost"
        cls.db.config.MAIL_DEBUG = "../_test_tracker_mail.log"
        cls.db.config.WEB_CSRF_ENFORCE_HEADER_ORIGIN = "required"
        cls.db.config.WEB_ALLOWED_API_ORIGINS = "https://client.com"
        
        cls.db.config['WEB_CSRF_ENFORCE_HEADER_X-REQUESTED-WITH'] = "required"

        # enable static precompressed files
        cls.db.config.WEB_USE_PRECOMPRESSED_FILES = 1

        cls.db.config.save()

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
        '''The wsgi app to start'''
        if _py3:
            return validator(RequestDispatcher(self.dirname))
        else:
            # wsgiref/validator.py InputWrapper::readline is broke and
            # doesn't support the max bytes to read argument.
            return RequestDispatcher(self.dirname)


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
        """ Roundup only handles one simple two number range.
            Range: 10-20

            The following are not supported.
            Range: 10-20, 25-30
            Range: 10-

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

        # conditional request 11 bytes since etag matches 206 code
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
        hdrs['If-Range'] = etag[2:]  # bad tag
        f = requests.get(self.url_base() + "/@@file/style.css", headers=hdrs)
        self.assertEqual(f.status_code, 200)
        # not checking content length since it could be compressed
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
                             headers = {'content-type': ""})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 404)

    def test_rest_login_rate_limit(self):
        """login rate limit applies to api endpoints. Only failure
            logins count though. So log in 10 times in a row
            to verify that valid username/passwords aren't limited.
        """

        for i in range(10):
            # use basic auth for rest endpoint
        
            f = requests.options(self.url_base() + '/rest/data',
                                 auth=('admin', 'sekrit'),
                                 headers = {'content-type': ""}
            )
            print(f.status_code)
            print(f.headers)
            
            self.assertEqual(f.status_code, 204)
            expected = { 'Access-Control-Allow-Origin': '*',
                         'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                         'Allow': 'OPTIONS, GET',
                         'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Credentials': 'true',
            }

        for i in range(10):
            # use basic auth for rest endpoint
        
            f = requests.options(self.url_base() + '/rest/data',
                                 auth=('admin', 'ekrit'),
                                 headers = {'content-type': ""}
            )
            print(i, f.status_code)
            print(f.headers)
            print(f.text)

            self.assertEqual(f.status_code, 401)

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
        expected = { 'Content-Type': 'application/javascript',
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
        expected = { 'Content-Type': 'application/javascript',
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
        expected = { 'Content-Type': 'application/javascript',
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
        expected = { 'Content-Type': 'application/javascript',
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
                                        'Origin': 'ZZZZ'})
        print(f.status_code)
        print(f.headers)

        # NOTE: not compressed payload too small
        self.assertEqual(f.status_code, 400)
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Credentials': 'true',
                     'Access-Control-Allow-Origin': 'ZZZZ',
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
        expected = { 'Content-Type': 'application/javascript',
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

    def test_new_issue_with_file_upload(self):
        # Set up session to manage cookies <insert blue monster here>
        session = requests.Session()
        session.headers.update({'Origin': 'http://localhost:9001'})

        # login using form
        login = {"__login_name": 'admin', '__login_password': 'sekrit', 
                 "@action": "login"}
        f = session.post(self.url_base()+'/', data=login)
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
        # login using form
        login = {"__login_name": 'admin', '__login_password': 'sekrit', 
                 "@action": "login"}
        f = session.post(self.url_base()+'/', data=login,
                          headers = {'Origin': "http://localhost:9001"}
)
        # look for change in text in sidebar post login
        self.assertIn('Hello, admin', f.text)

        r = session.post(url + 'file', files = c, data = d,
                          headers = {'x-requested-with': "rest",
                                     'Origin': "http://localhost:9001"}
        )
        self.assertEqual(r.status_code, 201)
        print(r.status_code)


