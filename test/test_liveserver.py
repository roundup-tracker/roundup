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
    port_range = (9001, 9010)  # default is (8080, 8090)

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
        self.assertTrue(b'Roundup' in f.content)
        self.assertTrue(b'Creator' in f.content)
