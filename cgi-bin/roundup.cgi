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
# $Id: roundup.cgi,v 1.11 2001-09-29 13:27:00 richard Exp $

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
    'test': '/tmp/roundup_test',
}

# Where to log debugging information to. Use an instance of DevNull if you
# don't want to log anywhere.
class DevNull:
    def write(self, info):
        pass
LOG = open('/var/log/roundup.cgi.log', 'a')
#LOG = DevNull()

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

def main(instance, out):
    from roundup import cgi_client
    db = instance.open('admin')
    auth = os.environ.get("HTTP_CGI_AUTHORIZATION", None)
    message = 'Unauthorised'
    if auth:
        import binascii
        l = binascii.a2b_base64(auth.split(' ')[1]).split(':')
        user = l[0]
        password = None
        if len(l) > 1:
            password = l[1]
        try:
            uid = db.user.lookup(user)
        except KeyError:
            auth = None
            message = 'Username not recognised'
        else:
            if password != db.user.get(uid, 'password'):
                message = 'Incorrect password'
                auth = None
    if not auth:
        out.write('Content-Type: text/html\n')
        out.write('Status: 401\n')
        out.write('WWW-Authenticate: basic realm="Roundup"\n\n')
        keys = os.environ.keys()
        keys.sort()
        out.write(message)
        return
    client = instance.Client(out, db, os.environ, user)
    try:
        client.main()
    except cgi_client.Unauthorised:
        out.write('Content-Type: text/html\n')
        out.write('Status: 403\n\n')
        out.write('Unauthorised')

def index(out):
    ''' Print up an index of the available instances
    '''
    w = out.write
    w("Content-Type: text/html\n\n")
    w('<html><head><title>Roundup instances index</title><head>\n')
    w('<body><h1>Roundup instances index</h1><ol>\n')
    for instance in ROUNDUP_INSTANCE_HOMES.keys():
        w('<li><a href="%s/index">%s</a>\n'%(urllib.quote(instance),
            instance))
    w('</ol></body></html>')

#
# Now do the actual CGI handling
# 
out, err = sys.stdout, sys.stderr
try:
    sys.stdout = sys.stderr = LOG
    import os, string
    import roundup.instance
    path = string.split(os.environ['PATH_INFO'], '/')
    instance = path[1]
    os.environ['PATH_INFO'] = string.join(path[2:], '/')
    if ROUNDUP_INSTANCE_HOMES.has_key(instance):
        instance_home = ROUNDUP_INSTANCE_HOMES[instance]
        instance = roundup.instance.open(instance_home)
        main(instance, out)
    else:
        index()
except:
    sys.stdout, sys.stderr = out, err
    out.write('Content-Type: text/html\n\n')
    cgitb.handler()
sys.stdout.flush()
sys.stdout, sys.stderr = out, err

#
# $Log: not supported by cvs2svn $
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
