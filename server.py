#!/usr/bin/python
""" HTTP Server that serves roundup.

Stolen from CGIHTTPServer

$Id: server.py,v 1.5 2001-07-20 12:33:06 richard Exp $

"""
import sys
if int(sys.version[0]) < 2:
    print "Content-Type: text/plain\n"
    print "Roundup requires Python 2.0 or newer."

__version__ = "0.1"

__all__ = ["RoundupRequestHandler"]

import os, urllib, StringIO, traceback, cgi, binascii
import BaseHTTPServer
import SimpleHTTPServer
import date, hyperdb, template, roundupdb, roundup_cgi
import cgitb

class RoundupRequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
    def send_head(self):
        """Version of send_head that support CGI scripts"""
        return self.run_cgi()

    def run_cgi(self):
        """Execute a CGI script."""
        rest = self.path
        i = rest.rfind('?')
        if i >= 0:
            rest, query = rest[:i], rest[i+1:]
        else:
            query = ''

        # Set up the CGI environment
        env = {}
        env['REQUEST_METHOD'] = self.command
        env['PATH_INFO'] = urllib.unquote(rest)
        if query:
            env['QUERY_STRING'] = query
        host = self.address_string()
        if self.headers.typeheader is None:
            env['CONTENT_TYPE'] = self.headers.type
        else:
            env['CONTENT_TYPE'] = self.headers.typeheader
        length = self.headers.getheader('content-length')
        if length:
            env['CONTENT_LENGTH'] = length
        co = filter(None, self.headers.getheaders('cookie'))
        if co:
            env['HTTP_COOKIE'] = ', '.join(co)
        env['SCRIPT_NAME'] = ''
        env['SERVER_NAME'] = self.server.server_name
        env['SERVER_PORT'] = str(self.server.server_port)

        decoded_query = query.replace('+', ' ')

        # if root, setuid to nobody
        if not os.getuid():
            nobody = nobody_uid()
            os.setuid(nobody)

        # TODO check for file timestamp changes
        reload(date)
        reload(hyperdb)
        reload(roundupdb)
        reload(template)
        reload(roundup_cgi)

        # initialise the roundupdb, check for auth
        db = roundupdb.openDB('db', 'admin')
        message = 'Unauthorised'
        auth = self.headers.getheader('authorization')
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
        db.close()
        del db
        if not auth:
            self.send_response(401)
            self.send_header('Content-Type', 'text/html')
            self.send_header('WWW-Authenticate', 'basic realm="Roundup"')
            self.end_headers()
            self.wfile.write(message)
            return

        self.send_response(200, "Script output follows")

        # do the roundup thang
        save_stdin = sys.stdin
        try:
            sys.stdin = self.rfile
            client = roundup_cgi.Client(self.wfile, env, user)
            client.main()
        except roundup_cgi.Unauthorised:
            self.wfile.write('Content-Type: text/html\n')
            self.wfile.write('Status: 403\n')
            self.wfile.write('Unauthorised')
        except:
            try:
                reload(cgitb)
                self.wfile.write(cgitb.breaker())
                self.wfile.write(cgitb.html())
            except:
                self.wfile.write("Content-Type: text/html\n\n")
                self.wfile.write("<pre>")
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                self.wfile.write(cgi.escape(s.getvalue()))
                self.wfile.write("</pre>\n")
        sys.stdin = save_stdin
    do_POST = run_cgi


nobody = None

def nobody_uid():
    """Internal routine to get nobody's uid"""
    global nobody
    if nobody:
        return nobody
    try:
        import pwd
    except ImportError:
        return -1
    try:
        nobody = pwd.getpwnam('nobody')[2]
    except KeyError:
        nobody = 1 + max(map(lambda x: x[2], pwd.getpwall()))
    return nobody

def main():
    from config import HTTP_HOST, HTTP_PORT
    address = (HTTP_HOST, HTTP_PORT)
    httpd = BaseHTTPServer.HTTPServer(address, RoundupRequestHandler)
    print 'Roundup server started on', address
    httpd.serve_forever()

if __name__ == '__main__':
    main()

#
# $Log: not supported by cvs2svn $
# Revision 1.4  2001/07/19 10:43:01  anthonybaxter
# HTTP_HOST and HTTP_PORT config options.
#
# Revision 1.3  2001/07/19 06:27:07  anthonybaxter
# fixing (manually) the (dollarsign)Log(dollarsign) entries caused by
# my using the magic (dollarsign)Id(dollarsign) and (dollarsign)Log(dollarsign)
# strings in a commit message. I'm a twonk.
#
# Also broke the help string in two.
#
# Revision 1.2  2001/07/19 05:52:22  anthonybaxter
# Added CVS keywords Id and Log to all python files.
#
#

