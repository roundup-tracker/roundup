# mod_python interface for Roundup Issue Tracker
#
# This module is free software, you may redistribute it
# and/or modify under the same terms as Python.
#
# This module provides Roundup Web User Interface
# using mod_python Apache module.  Initially written
# with python 2.3.3, mod_python 3.1.3, roundup 0.7.0.
#
# This module operates with only one tracker
# and must be placed in the tracker directory.
#
# History (most recent first):
# 11-jul-2004 [als] added 'TrackerLanguage' option;
#                   pass message translator to the tracker client instance
# 04-jul-2004 [als] tracker lookup moved from module global to request handler;
#                   use PythonOption TrackerHome (configured in apache)
#                   to open the tracker
# 06-may-2004 [als] use cgi.FieldStorage from Python library
#                   instead of mod_python FieldStorage
# 29-apr-2004 [als] created

__version__ = "$Revision: 1.6 $"[11:-2]
__date__ = "$Date: 2006-11-09 00:36:21 $"[7:-2]

import cgi
import os

from mod_python import apache

import roundup.instance
from roundup.cgi import TranslationService

class Headers(dict):

    """HTTP headers wrapper"""

    def __init__(self, headers):
        """Initialize with `apache.table`"""
        super(Headers, self).__init__(headers)
        self.getheader = self.get

class Request(object):

    """`apache.Request` object wrapper providing roundup client interface"""

    def __init__(self, request):
        """Initialize with `apache.Request` object"""
        self._req = request
        # .headers.getheader()
        self.headers = Headers(request.headers_in)
        # .wfile.write()
        self.wfile = self._req

    def start_response(self, headers, response):
        self.send_response(response)
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()

    def send_response(self, response_code):
        """Set HTTP response code"""
        self._req.status = response_code

    def send_header(self, name, value):
        """Set output header"""
        # value may be an instance of roundup.cgi.exceptions.HTTPException
        value = str(value)
        # XXX default content_type is "text/plain",
        #   and ain't overrided by "Content-Type" header
        if name == "Content-Type":
            self._req.content_type = value
        else:
            self._req.headers_out.add(name, value)

    def end_headers(self):
        """NOOP. There aint no such thing as 'end_headers' in mod_python"""
        pass

 
    def sendfile(self, filename, offset = 0, len = -1):
        """Send 'filename' to the user."""

        return self._req.sendfile(filename, offset, len)


def handler(req):
    """HTTP request handler"""
    _options = req.get_options()
    _home = _options.get("TrackerHome")
    _lang = _options.get("TrackerLanguage")
    _timing = _options.get("TrackerTiming", "no")
    if _timing.lower() in ("no", "false"):
        _timing = ""
    _debug = _options.get("TrackerDebug", "no")
    _debug = _debug.lower() not in ("no", "false")
    if not (_home and os.path.isdir(_home)):
        apache.log_error(
            "PythonOption TrackerHome missing or invalid for %(uri)s"
            % {'uri': req.uri})
        return apache.HTTP_INTERNAL_SERVER_ERROR
    _tracker = roundup.instance.open(_home, not _debug)
    # create environment
    # Note: cookies are read from HTTP variables, so we need all HTTP vars
    req.add_common_vars()
    _env = dict(req.subprocess_env)
    # XXX classname must be the first item in PATH_INFO.  roundup.cgi does:
    #       path = string.split(os.environ.get('PATH_INFO', '/'), '/')
    #       os.environ['PATH_INFO'] = string.join(path[2:], '/')
    #   we just remove the first character ('/')
    _env["PATH_INFO"] = req.path_info[1:]
    if _timing:
        _env["CGI_SHOW_TIMING"] = _timing
    _form = cgi.FieldStorage(req, environ=_env)
    _client = _tracker.Client(_tracker, Request(req), _env, _form,
        translator=TranslationService.get_translation(_lang,
            tracker_home=_home))
    _client.main()
    return apache.OK

# vim: set et sts=4 sw=4 :
