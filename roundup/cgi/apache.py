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
# mod_python is deprecated and not well tested with release 2.0 of
# roundup. mod_wsgi is the preferred interface. It may not work
# with python3.

# The patch from https://issues.roundup-tracker.org/issue2550821
# is included. Look for this url below. It is not tested, but
# we assume it's safe and syntax it seems ok.

import cgi
import os
import threading

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

    def sendfile(self, filename, offset=0, len=-1):
        """Send 'filename' to the user."""

        return self._req.sendfile(filename, offset, len)


__tracker_cache = {}
"""A cache of optimized tracker instances.

The keys are strings giving the directories containing the trackers.
The values are tracker instances."""

__tracker_cache_lock = threading.Lock()
"""A lock used to guard access to the cache."""


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

    # We do not need to take a lock here (the fast path) because reads
    # from dictionaries are atomic.
    if not _debug and _home in __tracker_cache:
        _tracker = __tracker_cache[_home]
    else:
        if not (_home and os.path.isdir(_home)):
            apache.log_error(
                "PythonOption TrackerHome missing or invalid for %(uri)s"
                % {'uri': req.uri})
            return apache.HTTP_INTERNAL_SERVER_ERROR
        if _debug:
            _tracker = roundup.instance.open(_home, optimize=0)
        else:
            __tracker_cache_lock.acquire()
            try:
                # The tracker may have been added while we were acquiring
                # the lock.
                if _home in __tracker_cache:
                    _tracker = __tracker_cache[_home]
                else:
                    _tracker = roundup.instance.open(_home, optimize=1)
                    __tracker_cache[_home] = _tracker
            finally:
                __tracker_cache_lock.release()
    # create environment
    # Note: cookies are read from HTTP variables, so we need all HTTP vars

    # https://issues.roundup-tracker.org/issue2550821
    # Release 3.4 of mod_python uses add_cgi_vars() and depricates
    # add_common_vars. So try to use the add_cgi_vars and if it fails
    # with AttributeError because we are running an older mod_apache without
    # that function, fallback to add_common_vars.
    try:
        req.add_cgi_vars()
    except AttributeError:
        req.add_common_vars()

    _env = dict(req.subprocess_env)
    # XXX classname must be the first item in PATH_INFO.  roundup.cgi does:
    #       path = os.environ.get('PATH_INFO', '/').split('/')
    #       os.environ['PATH_INFO'] = '/'.join(path[2:])
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
