# WSGI interface for Roundup Issue Tracker
#
# This module is free software, you may redistribute it
# and/or modify under the same terms as Python.
#

import os
import weakref

from contextlib import contextmanager

from roundup.anypy.html import html_escape

import roundup.instance
from roundup.cgi import TranslationService
from roundup.anypy import http_
from roundup.anypy.strings import s2b

from roundup.cgi.client import BinaryFieldStorage

BaseHTTPRequestHandler = http_.server.BaseHTTPRequestHandler
DEFAULT_ERROR_MESSAGE = http_.server.DEFAULT_ERROR_MESSAGE


class Headers(object):
    """ Idea more or less stolen from the 'apache.py' in same directory.
        Except that wsgi stores http headers in environment.
    """
    def __init__(self, environ):
        self.environ = environ

    def mangle_name(self, name):
        """ Content-Type is handled specially, it doesn't have a HTTP_
            prefix in cgi.
        """
        n = name.replace('-', '_').upper()
        if n == 'CONTENT_TYPE':
            return n
        return 'HTTP_' + n

    def get(self, name, default=None):
        return self.environ.get(self.mangle_name(name), default)
    getheader = get


class Writer(object):
    '''Perform a start_response if need be when we start writing.'''
    def __init__(self, request):
        self.request = request  #weakref.ref(request)

    def write(self, data):
        f = self.request.get_wfile()
        self.write = f
        return self.write(data)


class RequestHandler(object):
    def __init__(self, environ, start_response):
        self.__start_response = start_response
        self.__wfile = None
        self.headers = Headers(environ)
        self.rfile, self.wfile = None, Writer(self)

    def start_response(self, headers, response_code):
        """Set HTTP response code"""
        message, explain = BaseHTTPRequestHandler.responses[response_code]
        self.__wfile = self.__start_response('%d %s' % (response_code,
                                                        message), headers)

    def get_wfile(self):
        if self.__wfile is None:
            raise ValueError('start_response() not called')
        return self.__wfile


class RequestDispatcher(object):
    def __init__(self, home, debug=False, timing=False, lang=None):
        assert os.path.isdir(home), '%r is not a directory' % (home,)
        self.home = home
        self.debug = debug
        self.timing = timing
        if lang:
            self.translator = TranslationService.get_translation(lang,
                tracker_home=home)
        else:
            self.translator = None
        self.preload()

    def __call__(self, environ, start_response):
        """Initialize with `apache.Request` object"""
        request = RequestHandler(environ, start_response)

        if environ['REQUEST_METHOD'] == 'OPTIONS':
            if environ["PATH_INFO"][:5] == "/rest":
                # rest does support options
                # This I hope will result in self.form=None
                environ['CONTENT_LENGTH'] = 0
            else:
                code = 501
                message, explain = BaseHTTPRequestHandler.responses[code]
                request.start_response([('Content-Type', 'text/html')],
                                       code)
                request.wfile.write(s2b(DEFAULT_ERROR_MESSAGE % locals()))
                return []

        # need to strip the leading '/'
        environ["PATH_INFO"] = environ["PATH_INFO"][1:]
        if self.timing:
            environ["CGI_SHOW_TIMING"] = self.timing

        if environ['REQUEST_METHOD'] in ("OPTIONS", "DELETE"):
            # these methods have no data. When we init tracker.Client
            # set form to None to get a properly initialized empty
            # form.
            form = None
        else:
            form = BinaryFieldStorage(fp=environ['wsgi.input'], environ=environ)

        with self.get_tracker() as tracker:
            client = tracker.Client(tracker, request, environ, form,
                                    self.translator)
            try:
                client.main()
            except roundup.cgi.client.NotFound:
                request.start_response([('Content-Type', 'text/html')], 404)
                request.wfile.write(s2b('Not found: %s' % 
                                        html_escape(client.path)))

        # all body data has been written using wfile
        return []

    def preload(self):
        """ Trigger pre-loading of imports and templates """
        with self.get_tracker():
            pass

    @contextmanager
    def get_tracker(self):
        # get a new instance for each request
        yield roundup.instance.open(self.home, not self.debug)
