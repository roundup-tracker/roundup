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
# $Id: roundup.cgi,v 1.16 2001-11-01 22:04:37 richard Exp $

# python version check
import sys
if int(sys.version[0]) < 2:
    print "Content-Type: text/plain\n"
    print "Roundup requires Python 2.0 or newer."
    sys.exit(0)

#
##  Configuration
#

# This indicates where the Roundup instance lives
ROUNDUP_INSTANCE_HOMES = {
    'demo': '/var/roundup/instances/demo',
}

# Where to log debugging information to. Use an instance of DevNull if you
# don't want to log anywhere.
class DevNull:
    def write(self, info):
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
    from roundup import cgitb
except:
    print "Content-Type: text/html\n"
    print "Failed to import cgitb.<pre>"
    s = StringIO.StringIO()
    traceback.print_exc(None, s)
    print cgi.escape(s.getvalue()), "</pre>"

class RequestWrapper:
    '''Used to make the CGI server look like a BaseHTTPRequestHandler
    '''
    def __init__(self, wfile):
        self.wfile = wfile
    def send_response(self, code):
        self.wfile.write('Status: %s\r\n'%code)
    def send_header(self, keyword, value):
        self.wfile.write("%s: %s\r\n" % (keyword, value))
    def end_headers(self, keyword, value):
        self.wfile.write("\r\n")

def main(out, err):
    import os, string
    import roundup.instance
    path = string.split(os.environ.get('PATH_INFO', '/'), '/')
    instance = path[1]
    os.environ['INSTANCE_NAME'] = instance
    os.environ['PATH_INFO'] = string.join(path[2:], '/')
    request = RequestWrapper(out)
    if ROUNDUP_INSTANCE_HOMES.has_key(instance):
        instance_home = ROUNDUP_INSTANCE_HOMES[instance]
        instance = roundup.instance.open(instance_home)
        from roundup import cgi_client
        client = instance.Client(instance, request, os.environ)
        try:
            client.main()
        except cgi_client.Unauthorised:
            request.send_response(403)
            request.send_header('Content-Type', 'text/html')
            request.end_headers()
            out.write('Unauthorised')
        except cgi_client.NotFound:
            request.send_response(404)
            request.send_header('Content-Type', 'text/html')
            request.end_headers()
            out.write('Not found: %s'%client.path)
    else:
        import urllib
        request.send_response(200)
        request.send_header('Content-Type', 'text/html')
        w = request.wfile.write
        w('<html><head><title>Roundup instances index</title></head>\n')
        w('<body><h1>Roundup instances index</h1><ol>\n')
        for instance in ROUNDUP_INSTANCE_HOMES.keys():
            w('<li><a href="%s/%s/index">%s</a>\n'%(
                os.environ['SCRIPT_NAME'], urllib.quote(instance),
                cgi.escape(instance)))
        w('</ol></body></html>')

#
# Now do the actual CGI handling
# 
out, err = sys.stdout, sys.stderr
try:
    sys.stdout = sys.stderr = LOG
    main(out, err)
except SystemExit:
    pass
except:
    sys.stdout, sys.stderr = out, err
    out.write('Content-Type: text/html\n\n')
    cgitb.handler()
sys.stdout.flush()
sys.stdout, sys.stderr = out, err

#
# $Log: not supported by cvs2svn $
# Revision 1.15  2001/10/29 23:55:44  richard
# Fix to CGI top-level index (thanks Juergen Hermann)
#
# Revision 1.14  2001/10/27 00:22:35  richard
# Fixed some URL issues in roundup.cgi, again thanks Juergen Hermann.
#
# Revision 1.13  2001/10/05 02:23:24  richard
#  . roundup-admin create now prompts for property info if none is supplied
#    on the command-line.
#  . hyperdb Class getprops() method may now return only the mutable
#    properties.
#  . Login now uses cookies, which makes it a whole lot more flexible. We can
#    now support anonymous user access (read-only, unless there's an
#    "anonymous" user, in which case write access is permitted). Login
#    handling has been moved into cgi_client.Client.main()
#  . The "extended" schema is now the default in roundup init.
#  . The schemas have had their page headings modified to cope with the new
#    login handling. Existing installations should copy the interfaces.py
#    file from the roundup lib directory to their instance home.
#  . Incorrectly had a Bizar Software copyright on the cgitb.py module from
#    Ping - has been removed.
#  . Fixed a whole bunch of places in the CGI interface where we should have
#    been returning Not Found instead of throwing an exception.
#  . Fixed a deviation from the spec: trying to modify the 'id' property of
#    an item now throws an exception.
#
# Revision 1.12  2001/10/01 05:55:41  richard
# Fixes to the top-level index
#
# Revision 1.11  2001/09/29 13:27:00  richard
# CGI interfaces now spit up a top-level index of all the instances they can
# serve.
#
# Revision 1.10  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.9  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.8  2001/08/05 07:43:52  richard
# Instances are now opened by a special function that generates a unique
# module name for the instances on import time.
#
# Revision 1.7  2001/08/03 01:28:33  richard
# Used the much nicer load_package, pointed out by Steve Majewski.
#
# Revision 1.6  2001/08/03 00:59:34  richard
# Instance import now imports the instance using imp.load_module so that
# we can have instance homes of "roundup" or other existing python package
# names.
#
# Revision 1.5  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.4  2001/07/23 04:47:27  anthonybaxter
# renamed ROUNDUPS to ROUNDUP_INSTANCE_HOMES
# sys.exit(0) if python version wrong.
#
# Revision 1.3  2001/07/23 04:33:30  richard
# brought the CGI instance config dict in line with roundup-server
#
# Revision 1.2  2001/07/23 04:31:40  richard
# Fixed the roundup CGI script for updates to cgi_client.py
#
# Revision 1.1  2001/07/22 11:47:07  richard
# More Grande Splite
#
#
# vim: set filetype=python ts=4 sw=4 et si
