#!/usr/bin/env python

# $Id: roundup.cgi,v 1.1 2001-07-22 11:47:07 richard Exp $

# python version check
import sys
if int(sys.version[0]) < 2:
    print "Content-Type: text/plain\n"
    print "Roundup requires Python 2.0 or newer."

#
##  Configuration
#

# This indicates where the Roundup instance lives
ROUNDUPS = {
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
    client = instance.Client(out, os.environ, user)
    try:
        client.main()
    except cgi_client.Unauthorised:
        out.write('Content-Type: text/html\n')
        out.write('Status: 403\n\n')
        out.write('Unauthorised')

#
# Now do the actual CGI handling
# 
out, err = sys.stdout, sys.stderr
try:
    sys.stdout = sys.stderr = LOG
    import os, string
    instance = string.split(os.environ['PATH_INFO'], '/')[1]
    if ROUNDUPS.has_key(instance):
        instance_home = ROUNDUPS[instance]
        sys.path.insert(0, instance_home)
        try:
            instance = __import__(instance)
        finally:
            del sys.path[0]
    else:
        raise ValueError, 'No such instance "%s"'%instance
    main(instance, out)
except:
    sys.stdout, sys.stderr = out, err
    out.write('Content-Type: text/html\n\n')
    cgitb.handler()
sys.stdout.flush()
sys.stdout, sys.stderr = out, err

#
# $Log: not supported by cvs2svn $
#
