import shutil, errno, pytest, json, gzip, os

from roundup.anypy.strings import b2s
from roundup.cgi.wsgi_handler import RequestDispatcher
from .wsgi_liveserver import LiveServerTestCase
from . import db_test_base

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

@skip_requests
class SimpleTest(LiveServerTestCase):
    # have chicken and egg issue here. Need to encode the base_url
    # in the config file but we don't know it until after
    # the server is started nd has read the config.ini.
    # so only allow one port number
    port_range = (9001, 9001)  # default is (8080, 8090)

    dirname = '_test_instance'
    backend = 'anydbm'
    
    @classmethod
    def setup_class(cls):
        '''All test in this class use the same roundup instance.
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
        cls.db.config.MAIL_DEBUG = "../mail.log.t"

        # enable static precompressed files
        cls.db.config.WEB_USE_PRECOMPRESSED_FILES = 1

        cls.db.config.save()

        cls.db.commit()
        cls.db.close()

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

    def create_app(self):
        '''The wsgi app to start'''
        return RequestDispatcher(self.dirname)

    def test_start_page(self):
        """ simple test that verifies that the server can serve a start page.
        """
        f = requests.get(self.url_base())
        self.assertEqual(f.status_code, 200)
        self.assertTrue(b'Roundup' in f.content)
        self.assertTrue(b'Creator' in f.content)


    def test_rest_invalid_method_collection(self):
        # use basic auth for rest endpoint
        f = requests.put(self.url_base() + '/rest/data/user',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                             'x-requested-with': "rest"})
        print(f.status_code)
        print(f.headers)
        print(f.content)

        self.assertEqual(f.status_code, 405)
        expected = { 'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'DELETE, GET, OPTIONS, POST',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
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
                             headers = {'content-type': ""})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected = { 'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

    def test_rest_endpoint_data_options(self):
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
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

    def test_rest_endpoint_collection_options(self):
        # use basic auth for rest endpoint
        f = requests.options(self.url_base() + '/rest/data/user',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': ""})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected = { 'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST',
                     'Access-Control-Allow-Methods': 'OPTIONS, GET, POST',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)


    def test_rest_endpoint_item_options(self):

        f = requests.options(self.url_base() + '/rest/data/user/1',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': ""})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected = { 'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

    def test_rest_endpoint_attribute_options(self):
        # use basic auth for rest endpoint
        f = requests.options(self.url_base() + '/rest/data/user/1/username',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': ""})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected = { 'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
        }

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)

        ## test a read only property.

        f = requests.options(self.url_base() + '/rest/data/user/1/creator',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': ""})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 204)
        expected1 = dict(expected)
        expected1['Allow'] = 'OPTIONS, GET'

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
        expected = { 'Content-Type': 'application/javascript',
                     'Vary': 'Accept-Encoding',
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
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH'
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


    def test_compression_gzip(self):
        # use basic auth for rest endpoint
        f = requests.get(self.url_base() + '/rest/data/user/1/username',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Accept-Encoding': 'gzip, foo',
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Content-Encoding': 'gzip',
                     'Vary': 'Accept-Encoding',
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

        # verify that ETag header ends with -gzip
        try:
            self.assertRegex(f.headers['ETag'], r'^"[0-9a-f]{32}-gzip"$')
        except AttributeError:
            # python2 no assertRegex so try substring match
            self.assertEqual(33, f.headers['ETag'].rindex('-gzip"'))

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)



        # use basic auth for rest endpoint, error case, bad attribute
        f = requests.get(self.url_base() + '/rest/data/user/1/foo',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Accept-Encoding': 'gzip, foo',
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        # NOTE: not compressed payload too small
        self.assertEqual(f.status_code, 400)
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
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
                         headers = { 'Accept-Encoding': 'gzip, foo',
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'application/javascript',
                     'Content-Encoding': 'gzip',
                     'Vary': 'Accept-Encoding',
        }

        # check first few bytes.
        self.assertEqual(b2s(f.content[0:25]), '// User Editing Utilities')

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)

        # test file x-fer
        f = requests.get(self.url_base() + '/user1',
                         headers = { 'Accept-Encoding': 'gzip, foo',
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'text/html; charset=utf-8',
                     'Content-Encoding': 'gzip',
                     'Vary': 'Accept-Encoding',
        }

        # check first few bytes.
        self.assertEqual(b2s(f.content[0:25]), '<!-- dollarId: user.item,')

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)

    @skip_brotli
    def test_compression_br(self):
        # use basic auth for rest endpoint
        f = requests.get(self.url_base() + '/rest/data/user/1/username',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Accept-Encoding': 'br, foo',
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Content-Encoding': 'br',
                     'Vary': 'Accept-Encoding',
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
            json_dict = json.loads(f.content)
        except (ValueError, TypeError):
            # Handle error from trying to load compressed data
            json_dict = json.loads(b2s(brotli.decompress(f.content)))

        # etag wil not match, creation date different
        del(json_dict['data']['@etag']) 

        # type is "class 'str'" under py3, "type 'str'" py2
        # just skip comparing it.
        del(json_dict['data']['type']) 

        self.assertDictEqual(json_dict, content)

        # verify that ETag header ends with -br
        try:
            self.assertRegex(f.headers['ETag'], r'^"[0-9a-f]{32}-br"$')
        except AttributeError:
            # python2 no assertRegex so try substring match
            self.assertEqual(33, f.headers['ETag'].rindex('-br"'))

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)



        # use basic auth for rest endpoint, error case, bad attribute
        f = requests.get(self.url_base() + '/rest/data/user/1/foo',
                             auth=('admin', 'sekrit'),
                             headers = {'Accept-Encoding': 'br, foo',
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        # Note: not compressed payload too small
        self.assertEqual(f.status_code, 400)
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
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
                         headers = { 'Accept-Encoding': 'br, foo',
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'application/javascript',
                     'Content-Encoding': 'br',
                     'Vary': 'Accept-Encoding',
        }

        try:
           from urllib3.response import BrotliDecoder
           # requests has decoded br to text for me
           data = f.content
        except ImportError:
            # I need to decode
            data = brotli.decompress(f.content)

        # check first few bytes.
        self.assertEqual(b2s(data)[0:25], '// User Editing Utilities')

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)

        # test file x-fer
        f = requests.get(self.url_base() + '/user1',
                         headers = { 'Accept-Encoding': 'br, foo',
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'text/html; charset=utf-8',
                     'Content-Encoding': 'br',
                     'Vary': 'Accept-Encoding',
        }

        try:
           from urllib3.response import BrotliDecoder
           # requests has decoded br to text for me
           data = f.content
        except ImportError:
            # I need to decode
            data = brotli.decompress(f.content)

        # check first few bytes.
        self.assertEqual(b2s(data)[0:25],
                         '<!-- dollarId: user.item,')

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)


    @skip_zstd
    def test_compression_zstd(self):
        # use basic auth for rest endpoint
        f = requests.get(self.url_base() + '/rest/data/user/1/username',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Accept-Encoding': 'zstd, foo',
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Content-Encoding': 'zstd',
                     'Vary': 'Accept-Encoding',
        }

        content_str = '''{ "data": {
                        "id": "1",
                        "link": "http://localhost:9001/rest/data/user/1/username",
                        "data": "admin"
                    }
        }'''
        content = json.loads(content_str)


        try:
            json_dict = json.loads(f.content)
        except (ValueError, UnicodeDecodeError, TypeError):
            # ValueError - raised by loads on compressed content python2
            # UnicodeDecodeError - raised by loads on compressed content
            #    python3
            json_dict = json.loads(b2s(zstd.decompress(f.content)))

        # etag wil not match, creation date different
        del(json_dict['data']['@etag']) 

        # type is "class 'str'" under py3, "type 'str'" py2
        # just skip comparing it.
        del(json_dict['data']['type']) 

        self.assertDictEqual(json_dict, content)

        # verify that ETag header ends with -zstd
        try:
            self.assertRegex(f.headers['ETag'], r'^"[0-9a-f]{32}-zstd"$')
        except AttributeError:
            # python2 no assertRegex so try substring match
            self.assertEqual(33, f.headers['ETag'].rindex('-zstd"'))

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in f.headers.items() if key in expected }, expected)



        # use basic auth for rest endpoint, error case, bad attribute
        f = requests.get(self.url_base() + '/rest/data/user/1/foo',
                             auth=('admin', 'sekrit'),
                             headers = {'content-type': "",
                                        'Accept-Encoding': 'zstd, foo',
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        # Note: not compressed, payload too small
        self.assertEqual(f.status_code, 400)
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, PUT, DELETE, PATCH',
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
                         headers = { 'Accept-Encoding': 'zstd, foo',
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'application/javascript',
                     'Content-Encoding': 'zstd',
                     'Vary': 'Accept-Encoding',
        }

        # check first few bytes.
        self.assertEqual(b2s(zstd.decompress(f.content)[0:25]), '// User Editing Utilities')

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)

        # test file x-fer
        f = requests.get(self.url_base() + '/user1',
                         headers = { 'Accept-Encoding': 'zstd, foo',
                                     'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        expected = { 'Content-Type': 'text/html; charset=utf-8',
                     'Content-Encoding': 'zstd',
                     'Vary': 'Accept-Encoding',
        }

        # check first few bytes.
        self.assertEqual(b2s(zstd.decompress(f.content)[0:25]),
                         '<!-- dollarId: user.item,')

        # use dict comprehension to remove fields like date,
        # content-length etc. from f.headers.
        self.assertDictEqual({ key: value for (key, value) in
                               f.headers.items() if key in expected },
                             expected)

    def test_cache_control_css(self):
        f = requests.get(self.url_base() + '/@@file/style.css',
                             headers = {'content-type': "",
                                        'Accept': '*/*'})
        print(f.status_code)
        print(f.headers)

        self.assertEqual(f.status_code, 200)
        self.assertEqual(f.headers['Cache-Control'], 'public, max-age=4838400')

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

