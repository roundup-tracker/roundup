#!/usr/bin/env python

import sys
if int(sys.version[0]) < 2:
    print "Content-Type: text/plain\n"
    print "Roundup requires Python 2.0 or newer."

import os, traceback, StringIO, cgi, binascii

try:
    import cgitb
except:
    print "Content-Type: text/html\n"
    print "Failed to import cgitb"
    print "<pre>"
    s = StringIO.StringIO()
    traceback.print_exc(None, s)
    print cgi.escape(s.getvalue())
    print "</pre>"

# Force import first from the same directory where this script lives.
dir, name = os.path.split(sys.argv[0])
sys.path[:0] = [dir or "."]

def main(out):
    import config, roundupdb, roundup_cgi
    db = roundupdb.openDB(config.DATABASE, 'admin')
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
    client = roundup_cgi.Client(out, os.environ, user)
    try:
        client.main()
    except roundup_cgi.Unauthorised:
        out.write('Content-Type: text/html\n')
        out.write('Status: 403\n\n')
        out.write('Unauthorised')

out, err = sys.stdout, sys.stderr
try:
    import config, roundup_cgi
    sys.stdout = sys.stderr = open(config.LOG, 'a')
    main(out)
except:
    sys.stdout, sys.stderr = out, err
    out.write('Content-Type: text/html\n\n')
    cgitb.handler()
sys.stdout.flush()
sys.stdout, sys.stderr = out, err
