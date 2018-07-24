# WSGI interface for Roundup Issue Tracker
#
# This module is free software, you may redistribute it
# and/or modify under the same terms as Python.
#

import os
import cgi
import weakref

import roundup.instance
from roundup.cgi import TranslationService
from BaseHTTPServer import BaseHTTPRequestHandler, DEFAULT_ERROR_MESSAGE


class Writer(object):
    '''Perform a start_response if need be when we start writing.'''
    def __init__(self, request):
        self.request = request #weakref.ref(request)
    def write(self, data):
        f = self.request.get_wfile()
        self.write = f
        return f(data)

class RequestDispatcher(object):
    def __init__(self, home, debug=False, timing=False, lang=None):
        assert os.path.isdir(home), '%r is not a directory'%(home,)
        self.home = home
        self.debug = debug
        self.timing = timing
        if lang:
            self.translator = TranslationService.get_translation(lang,
                tracker_home=home)
        else:
            self.translator = None

    def __call__(self, environ, start_response):
        """Initialize with `apache.Request` object"""
        self.environ = environ
        request = RequestDispatcher(self.home, self.debug, self.timing)
        request.__start_response = start_response

        request.wfile = Writer(request)
        request.__wfile = None

        if environ ['REQUEST_METHOD'] == 'OPTIONS':
            code = 501
            message, explain = BaseHTTPRequestHandler.responses[code]
            request.start_response([('Content-Type', 'text/html'),
                ('Connection', 'close')], code)
            request.wfile.write(DEFAULT_ERROR_MESSAGE % locals())
            return []

        tracker = roundup.instance.open(self.home, not self.debug)

        # need to strip the leading '/'
        environ["PATH_INFO"] = environ["PATH_INFO"][1:]
        if request.timing:
            environ["CGI_SHOW_TIMING"] = request.timing

        form = cgi.FieldStorage(fp=environ['wsgi.input'], environ=environ)

        client = tracker.Client(tracker, request, environ, form,
            request.translator)
        try:
            client.main()
        except roundup.cgi.client.NotFound:
            request.start_response([('Content-Type', 'text/html')], 404)
            request.wfile.write('Not found: %s'%client.path)

        # all body data has been written using wfile
        return []

    def start_response(self, headers, response_code):
        """Set HTTP response code"""
        message, explain = BaseHTTPRequestHandler.responses[response_code]
        self.__wfile = self.__start_response('%d %s'%(response_code,
            message), headers)

    def get_wfile(self):
        if self.__wfile is None:
            raise ValueError('start_response() not called')
        return self.__wfile

