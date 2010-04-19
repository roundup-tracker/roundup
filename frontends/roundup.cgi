#!/usr/bin/env python
#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
# $Id: roundup.cgi,v 1.2 2006-12-11 23:36:15 richard Exp $

# python version check
from roundup import version_check
from roundup.i18n import _
import sys, time

#
##  Configuration
#

# Configuration can also be provided through the OS environment (or via
# the Apache "SetEnv" configuration directive). If the variables
# documented below are set, they _override_ any configuation defaults
# given in this file. 

# TRACKER_HOMES is a list of trackers, in the form
# "NAME=DIR<sep>NAME2=DIR2<sep>...", where <sep> is the directory path
# separator (";" on Windows, ":" on Unix). 

# Make sure the NAME part doesn't include any url-unsafe characters like 
# spaces, as these confuse the cookie handling in browsers like IE.

# ROUNDUP_LOG is the name of the logfile; if it's empty or does not exist,
# logging is turned off (unless you changed the default below). 

# DEBUG_TO_CLIENT specifies whether debugging goes to the HTTP server (via
# stderr) or to the web client (via cgitb).
DEBUG_TO_CLIENT = False

# This indicates where the Roundup tracker lives
TRACKER_HOMES = {
#    'example': '/path/to/example',
}

# Where to log debugging information to. Use an instance of DevNull if you
# don't want to log anywhere.
class DevNull:
    def write(self, info):
        pass
    def close(self):
        pass
    def flush(self):
        pass
#LOG = open('/var/log/roundup.cgi.log', 'a')
LOG = DevNull()

#
##  end configuration
#


#
# Set up the error handler
# 
try:
    import traceback, StringIO, cgi
    from roundup.cgi import cgitb
except:
    print "Content-Type: text/plain\n"
    print _("Failed to import cgitb!\n\n")
    s = StringIO.StringIO()
    traceback.print_exc(None, s)
    print s.getvalue()


#
# Check environment for config items
#
def checkconfig():
    import os, string
    global TRACKER_HOMES, LOG

    # see if there's an environment var. ROUNDUP_INSTANCE_HOMES is the
    # old name for it.
    if os.environ.has_key('ROUNDUP_INSTANCE_HOMES'):
        homes = os.environ.get('ROUNDUP_INSTANCE_HOMES')
    else:
        homes = os.environ.get('TRACKER_HOMES', '')
    if homes:
        TRACKER_HOMES = {}
        for home in string.split(homes, os.pathsep):
            try:
                name, dir = string.split(home, '=', 1)
            except ValueError:
                # ignore invalid definitions
                continue
            if name and dir:
                TRACKER_HOMES[name] = dir
                
    logname = os.environ.get('ROUNDUP_LOG', '')
    if logname:
        LOG = open(logname, 'a')

    # ROUNDUP_DEBUG is checked directly in "roundup.cgi.client"


#
# Provide interface to CGI HTTP response handling
#
class RequestWrapper:
    '''Used to make the CGI server look like a BaseHTTPRequestHandler
    '''
    def __init__(self, wfile):
        self.rfile = sys.stdin
        self.wfile = wfile
    def write(self, data):
        self.wfile.write(data)
    def send_response(self, code):
        self.write('Status: %s\r\n'%code)
    def send_header(self, keyword, value):
        self.write("%s: %s\r\n" % (keyword, value))
    def end_headers(self):
        self.write("\r\n")
    def start_response(self, headers, response):
        self.send_response(response)
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()

#
# Main CGI handler
#
def main(out, err):
    import os, string
    import roundup.instance
    path = string.split(os.environ.get('PATH_INFO', '/'), '/')
    request = RequestWrapper(out)
    request.path = os.environ.get('PATH_INFO', '/')
    tracker = path[1]
    os.environ['TRACKER_NAME'] = tracker
    os.environ['PATH_INFO'] = string.join(path[2:], '/')
    if TRACKER_HOMES.has_key(tracker):
        # redirect if we need a trailing '/'
        if len(path) == 2:
            request.send_response(301)
            # redirect
            if os.environ.get('HTTPS', '') == 'on':
                protocol = 'https'
            else:
                protocol = 'http'
            absolute_url = '%s://%s%s/'%(protocol, os.environ['HTTP_HOST'],
                os.environ.get('REQUEST_URI', ''))
            request.send_header('Location', absolute_url)
            request.end_headers()
            out.write('Moved Permanently')
        else:
            tracker_home = TRACKER_HOMES[tracker]
            tracker = roundup.instance.open(tracker_home)
            import roundup.cgi.client
            if hasattr(tracker, 'Client'):
                client = tracker.Client(tracker, request, os.environ)
            else:
                client = roundup.cgi.client.Client(tracker, request, os.environ)
            try:
                client.main()
            except roundup.cgi.client.Unauthorised:
                request.send_response(403)
                request.send_header('Content-Type', 'text/html')
                request.end_headers()
                out.write('Unauthorised')
            except roundup.cgi.client.NotFound:
                request.send_response(404)
                request.send_header('Content-Type', 'text/html')
                request.end_headers()
                out.write('Not found: %s'%client.path)

    else:
        import urllib
        request.send_response(200)
        request.send_header('Content-Type', 'text/html')
        request.end_headers()
        w = request.write
        w(_('<html><head><title>Roundup trackers index</title></head>\n'))
        w(_('<body><h1>Roundup trackers index</h1><ol>\n'))
        homes = TRACKER_HOMES.keys()
        homes.sort()
        for tracker in homes:
            w(_('<li><a href="%(tracker_url)s/index">%(tracker_name)s</a>\n')%{
                'tracker_url': os.environ['SCRIPT_NAME']+'/'+
                               urllib.quote(tracker),
                'tracker_name': cgi.escape(tracker)})
        w(_('</ol></body></html>'))

#
# Now do the actual CGI handling
#
out, err = sys.stdout, sys.stderr
try:
    # force input/output to binary (important for file up/downloads)
    if sys.platform == "win32":
        import os, msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    checkconfig()
    sys.stdout = sys.stderr = LOG
    main(out, err)
except SystemExit:
    pass
except:
    sys.stdout, sys.stderr = out, err
    out.write('Content-Type: text/html\n\n')
    if DEBUG_TO_CLIENT:
        cgitb.handler()
    else:
        out.write(cgitb.breaker())
        ts = time.ctime()
        out.write('''<p>%s: An error occurred. Please check
            the server log for more infomation.</p>'''%ts)
        print >> sys.stderr, 'EXCEPTION AT', ts
        traceback.print_exc(0, sys.stderr)

sys.stdout.flush()
sys.stdout, sys.stderr = out, err
LOG.close()

# vim: set filetype=python ts=4 sw=4 et si
