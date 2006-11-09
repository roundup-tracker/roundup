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
from BaseHTTPServer import BaseHTTPRequestHandler


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
        self.__start_response = start_response

        self.wfile = Writer(self)
        self.__wfile = None

        tracker = roundup.instance.open(self.home, not self.debug)

        # need to strip the leading '/'
        environ["PATH_INFO"] = environ["PATH_INFO"][1:]
        if self.timing:
            environ["CGI_SHOW_TIMING"] = self.timing

        form = cgi.FieldStorage(fp=environ['wsgi.input'], environ=environ)

        client = tracker.Client(tracker, self, environ, form,
            self.translator)
        try:
            client.main()
        except roundup.cgi.client.NotFound:
            self.start_response([('Content-Type', 'text/html')], 404)
            self.wfile.write('Not found: %s'%client.path)

        # all body data has been written using wfile
        return []

    def start_response(self, headers, response_code):
        """Set HTTP response code"""
        description = BaseHTTPRequestHandler.responses[response_code]
        self.__wfile = self.__start_response('%d %s'%(response_code,
            description), headers)

    def get_wfile(self):
        if self.__wfile is None:
            raise ValueError, 'start_response() not called'
        return self.__wfile

