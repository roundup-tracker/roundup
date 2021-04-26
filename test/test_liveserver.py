import shutil, errno, pytest

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
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, PUT, DELETE, PATCH',
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
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, PUT, DELETE, PATCH',
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
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, POST',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, PUT, DELETE, PATCH',
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
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, PUT, DELETE, PATCH',
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
        expected = { 'Content-Type': 'application/json',
                     'Access-Control-Allow-Origin': '*',
                     'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-HTTP-Method-Override',
                     'Allow': 'OPTIONS, GET, PUT, DELETE, PATCH',
                     'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, PUT, DELETE, PATCH',
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


