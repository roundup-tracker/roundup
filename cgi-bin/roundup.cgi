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
# $Id: roundup.cgi,v 1.24 2002-01-05 02:21:22 richard Exp $

# python version check
from roundup import version_check
from roundup.i18n import _
import sys

#
##  Configuration
#

# Configuration can also be provided through the OS environment (or via
# the Apache "SetEnv" configuration directive). If the variables
# documented below are set, they _override_ any configuation defaults
# given in this file. 

# ROUNDUP_INSTANCE_HOMES is a list of instances, in the form
# "NAME=DIR<sep>NAME2=DIR2<sep>...", where <sep> is the directory path
# separator (";" on Windows, ":" on Unix). 

# ROUNDUP_LOG is the name of the logfile; if it's empty or does not exist,
# logging is turned off (unless you changed the default below). 

# ROUNDUP_DEBUG is a debug level, currently only 0 (OFF) and 1 (ON) are
# used in the code. Higher numbers means more debugging output. 

# This indicates where the Roundup instance lives
ROUNDUP_INSTANCE_HOMES = {
    'demo': '/var/roundup/instances/demo',
}

# Where to log debugging information to. Use an instance of DevNull if you
# don't want to log anywhere.
class DevNull:
    def write(self, info):
        pass
    def close(self):
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
    print _("Failed to import cgitb.<pre>")
    s = StringIO.StringIO()
    traceback.print_exc(None, s)
    print cgi.escape(s.getvalue()), "</pre>"


#
# Check environment for config items
#
def checkconfig():
    import os, string
    global ROUNDUP_INSTANCE_HOMES, LOG

    homes = os.environ.get('ROUNDUP_INSTANCE_HOMES', '')
    if homes:
        ROUNDUP_INSTANCE_HOMES = {}
        for home in string.split(homes, os.pathsep):
            try:
                name, dir = string.split(home, '=', 1)
            except ValueError:
                # ignore invalid definitions
                continue
            if name and dir:
                ROUNDUP_INSTANCE_HOMES[name] = dir
                
    logname = os.environ.get('ROUNDUP_LOG', '')
    if logname:
        LOG = open(logname, 'a')

    # ROUNDUP_DEBUG is checked directly in "roundup.cgi_client"


#
# Provide interface to CGI HTTP response handling
#
class RequestWrapper:
    '''Used to make the CGI server look like a BaseHTTPRequestHandler
    '''
    def __init__(self, wfile):
        self.wfile = wfile
    def write(self, data):
        self.wfile.write(data)
    def send_response(self, code):
        self.write('Status: %s\r\n'%code)
    def send_header(self, keyword, value):
        self.write("%s: %s\r\n" % (keyword, value))
    def end_headers(self):
        self.write("\r\n")

#
# Main CGI handler
#
def main(out, err):
    import os, string
    import roundup.instance
    path = string.split(os.environ.get('PATH_INFO', '/'), '/')
    instance = path[1]
    os.environ['INSTANCE_NAME'] = instance
    os.environ['PATH_INFO'] = string.join(path[2:], '/')
    request = RequestWrapper(out)
    if ROUNDUP_INSTANCE_HOMES.has_key(instance):
        # redirect if we need a trailing '/'
        if len(path) == 2:
            request.send_response(301)
            absolute_url = 'http://%s%s/'%(os.environ['HTTP_HOST'],
                os.environ['REQUEST_URI'])
            request.send_header('Location', absolute_url)
            request.end_headers()
            out.write('Moved Permanently')
        else:
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
        request.end_headers()
        w = request.write
        w(_('<html><head><title>Roundup instances index</title></head>\n'))
        w(_('<body><h1>Roundup instances index</h1><ol>\n'))
        homes = ROUNDUP_INSTANCE_HOMES.keys()
        homes.sort()
        for instance in homes:
            w(_('<li><a href="%(instance_url)s/index">%(instance_name)s</a>\n')%{
                'instance_url': os.environ['SCRIPT_NAME']+'/'+urllib.quote(instance),
                'instance_name': cgi.escape(instance)})
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
    cgitb.handler()
sys.stdout.flush()
sys.stdout, sys.stderr = out, err
LOG.close()

#
# $Log: not supported by cvs2svn $
# Revision 1.23  2002/01/05 02:19:03  richard
# i18n'ification
#
# Revision 1.22  2001/12/13 00:20:01  richard
#  . Centralised the python version check code, bumped version to 2.1.1 (really
#    needs to be 2.1.2, but that isn't released yet :)
#
# Revision 1.21  2001/12/02 05:06:16  richard
# . We now use weakrefs in the Classes to keep the database reference, so
#   the close() method on the database is no longer needed.
#   I bumped the minimum python requirement up to 2.1 accordingly.
# . #487480 ] roundup-server
# . #487476 ] INSTALL.txt
#
# I also cleaned up the change message / post-edit stuff in the cgi client.
# There's now a clearly marked "TODO: append the change note" where I believe
# the change note should be added there. The "changes" list will obviously
# have to be modified to be a dict of the changes, or somesuch.
#
# More testing needed.
#
# Revision 1.20  2001/11/26 22:55:56  richard
# Feature:
#  . Added INSTANCE_NAME to configuration - used in web and email to identify
#    the instance.
#  . Added EMAIL_SIGNATURE_POSITION to indicate where to place the roundup
#    signature info in e-mails.
#  . Some more flexibility in the mail gateway and more error handling.
#  . Login now takes you to the page you back to the were denied access to.
#
# Fixed:
#  . Lots of bugs, thanks Roché and others on the devel mailing list!
#
# Revision 1.19  2001/11/22 00:25:10  richard
# quick fix for file uploads on windows in roundup.cgi
#
# Revision 1.18  2001/11/06 22:10:11  jhermann
# Added env config; fixed request wrapper & index list; sort list by key
#
# Revision 1.17  2001/11/06 21:51:19  richard
# Fixed HTTP headers for top-level index in CGI script
#
# Revision 1.16  2001/11/01 22:04:37  richard
# Started work on supporting a pop3-fetching server
# Fixed bugs:
#  . bug #477104 ] HTML tag error in roundup-server
#  . bug #477107 ] HTTP header problem
#
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
