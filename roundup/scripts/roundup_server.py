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
""" HTTP Server that serves roundup.

$Id: roundup_server.py,v 1.34 2003-11-12 23:29:17 richard Exp $
"""

# python version check
from roundup import version_check

import sys, os, urllib, StringIO, traceback, cgi, binascii, getopt, imp
import BaseHTTPServer, socket, errno

# Roundup modules of use here
from roundup.cgi import cgitb, client
import roundup.instance
from roundup.i18n import _

#
##  Configuration
#

# This indicates where the Roundup trackers live. They're given as NAME ->
# TRACKER_HOME, where the NAME part is used in the URL to select the
# appropriate reacker.
# Make sure the NAME part doesn't include any url-unsafe characters like 
# spaces, as these confuse the cookie handling in browsers like IE.
TRACKER_HOMES = {
#    'example': '/path/to/example',
}

ROUNDUP_USER = None


#
##  end configuration
#

import zlib, base64
favico = zlib.decompress(base64.decodestring('''
eJyVUk2IQVEUfn4yaRYjibdQZiVba/ZE2djIUmHWFjaKGVmIlY2iFMVG2ViQhXqFSP6iFFJvw4uF
LGdWd743mpeMn+a88917Oue7955z3qEoET6FQkHx8iahKDV2A8B7XgERRf/EKMSUzyf8ypbbnnQy
mWBdr9eVSkVw3tJGoxGNRpvNZigUyufzWPv9Pvwcx0UiERj7/V4g73Y7j8fTarWMRmO73U4kEkKI
YZhardbr9eLxuOD0+/2ZTMZisYjFYpqmU6kU799uN5tNMBg8HA7ZbPY8GaTh8/mEipRKpclk0ul0
NpvNarUmk0mWZS/yr9frcrmc+iMOh+NWydPp1Ov1SiSSc344HL7fKKfTiSN2u12tVqOcxWJxn6/V
ag0GAwxkrlKp5vP5fT7ulMlk6XRar9dLpVIUXi6Xb5Hxa1wul0ajKZVKsVjM7XYXCoVOp3OVPJvN
AoFAtVo1m825XO7hSODOYrH4kHbxxGAwwODBGI/H6DBs5LNara7yl8slGjIcDsHpdrunU6PRCAP2
r3fPdUcIYeyEfLSAJ0LeAUZHCAt8Al/8/kLIEWDB5YDj0wm8fAP6fVfo
'''.strip()))

class RoundupRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    TRACKER_HOMES = TRACKER_HOMES
    ROUNDUP_USER = ROUNDUP_USER

    def run_cgi(self):
        """ Execute the CGI command. Wrap an innner call in an error
            handler so all errors can be caught.
        """
        save_stdin = sys.stdin
        sys.stdin = self.rfile
        try:
            self.inner_run_cgi()
        except client.NotFound:
            self.send_error(404, self.path)
        except client.Unauthorised:
            self.send_error(403, self.path)
        except socket.timeout:
            s = StringIO.StringIO()
            traceback.print_exc(None, s)
            self.log_message('%s', s.getvalue())
        except:
            # it'd be nice to be able to detect if these are going to have
            # any effect...
            self.send_response(400)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            try:
                reload(cgitb)
                self.wfile.write(cgitb.breaker())
                self.wfile.write(cgitb.html())
            except:
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                self.wfile.write("<pre>")
                self.wfile.write(cgi.escape(s.getvalue()))
                self.wfile.write("</pre>\n")
        sys.stdin = save_stdin

    do_GET = do_POST = run_cgi

    def index(self):
        ''' Print up an index of the available trackers
        '''
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        w = self.wfile.write
        w(_('<html><head><title>Roundup trackers index</title></head>\n'))
        w(_('<body><h1>Roundup trackers index</h1><ol>\n'))
        keys = self.TRACKER_HOMES.keys()
        keys.sort()
        for tracker in keys:
            w(_('<li><a href="%(tracker_url)s/index">%(tracker_name)s</a>\n')%{
                'tracker_url': urllib.quote(tracker),
                'tracker_name': cgi.escape(tracker)})
        w(_('</ol></body></html>'))

    def inner_run_cgi(self):
        ''' This is the inner part of the CGI handling
        '''
        rest = self.path

        if rest == '/favicon.ico':
            raise client.NotFound

        i = rest.rfind('?')
        if i >= 0:
            rest, query = rest[:i], rest[i+1:]
        else:
            query = ''

        # no tracker - spit out the index
        if rest == '/':
            return self.index()

        # figure the tracker
        l_path = rest.split('/')
        tracker_name = urllib.unquote(l_path[1])

        # handle missing trailing '/'
        if len(l_path) == 2:
            self.send_response(301)
            # redirect - XXX https??
            protocol = 'http'
            url = '%s://%s%s/'%(protocol, self.headers['host'], self.path)
            self.send_header('Location', url)
            self.end_headers()
            self.wfile.write('Moved Permanently')
            return

        if self.TRACKER_HOMES.has_key(tracker_name):
            tracker_home = self.TRACKER_HOMES[tracker_name]
            tracker = roundup.instance.open(tracker_home)
        else:
            raise client.NotFound

        # figure out what the rest of the path is
        if len(l_path) > 2:
            rest = '/'.join(l_path[2:])
        else:
            rest = '/'

        # Set up the CGI environment
        env = {}
        env['TRACKER_NAME'] = tracker_name
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
        env['HTTP_AUTHORIZATION'] = self.headers.getheader('authorization')
        env['SCRIPT_NAME'] = ''
        env['SERVER_NAME'] = self.server.server_name
        env['SERVER_PORT'] = str(self.server.server_port)
        env['HTTP_HOST'] = self.headers['host']

        decoded_query = query.replace('+', ' ')

        # do the roundup thang
        c = tracker.Client(tracker, self, env)
        c.main()

    LOG_IPADDRESS = 1
    def address_string(self):
        if self.LOG_IPADDRESS:
            return self.client_address[0]
        else:
            host, port = self.client_address
            return socket.getfqdn(host)

def error():
    exc_type, exc_value = sys.exc_info()[:2]
    return _('Error: %s: %s' % (exc_type, exc_value))

def usage(message=''):
    print _('''%(message)s

Usage:
roundup-server [options] [name=tracker home]*

options:
 -n: sets the host name
 -p: sets the port to listen on
 -u: sets the uid to this user after listening on the port
 -g: sets the gid to this group after listening on the port
 -l: sets a filename to log to (instead of stdout)
 -d: sets a filename to write server PID to. This option causes the server 
     to run in the background. Note: on Windows the PID argument is needed,
     but ignored. The -l option *must* be specified if this option is.
 -N: log client machine names in access log instead of IP addresses (much
     slower)

name=tracker home:
   Sets the tracker home(s) to use. The name is how the tracker is
   identified in the URL (it's the first part of the URL path). The
   tracker home is the directory that was identified when you did
   "roundup-admin init". You may specify any number of these name=home
   pairs on the command-line. For convenience, you may edit the
   TRACKER_HOMES variable in the roundup-server file instead.
   Make sure the name part doesn't include any url-unsafe characters like 
   spaces, as these confuse the cookie handling in browsers like IE.
''')%locals()
    sys.exit(0)

def daemonize(pidfile):
    ''' Turn this process into a daemon.
        - make sure the sys.std(in|out|err) are completely cut off
        - make our parent PID 1

        Write our new PID to the pidfile.

        From A.M. Kuuchling (possibly originally Greg Ward) with
        modification from Oren Tirosh, and finally a small mod from me.
    '''
    # Fork once
    if os.fork() != 0:
        os._exit(0)

    # Create new session
    os.setsid()

    # Second fork to force PPID=1
    pid = os.fork()
    if pid:
        pidfile = open(pidfile, 'w')
        pidfile.write(str(pid))
        pidfile.close()
        os._exit(0)         

    os.chdir("/")         
    os.umask(0)

    # close off sys.std(in|out|err), redirect to devnull so the file
    # descriptors can't be used again
    devnull = os.open('/dev/null', 0)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)

def run(port=8080, success_message=None):
    ''' Script entry point - handle args and figure out what to to.
    '''
    # time out after a minute if we can
    import socket
    if hasattr(socket, 'setdefaulttimeout'):
        socket.setdefaulttimeout(60)

    hostname = ''
    pidfile = None
    logfile = None
    try:
        # handle the command-line args
        try:
            optlist, args = getopt.getopt(sys.argv[1:], 'n:p:u:d:l:hN')
        except getopt.GetoptError, e:
            usage(str(e))

        user = ROUNDUP_USER
        group = None
        for (opt, arg) in optlist:
            if opt == '-n': hostname = arg
            elif opt == '-p': port = int(arg)
            elif opt == '-u': user = arg
            elif opt == '-g': group = arg
            elif opt == '-d': pidfile = os.path.abspath(arg)
            elif opt == '-l': logfile = os.path.abspath(arg)
            elif opt == '-h': usage()
            elif opt == '-N': RoundupRequestHandler.LOG_IPADDRESS = 0

        if pidfile and not logfile:
            raise ValueError, _("logfile *must* be specified if pidfile is")
  
        # obtain server before changing user id - allows to use port <
        # 1024 if started as root
        address = (hostname, port)
        try:
            httpd = BaseHTTPServer.HTTPServer(address, RoundupRequestHandler)
        except socket.error, e:
            if e[0] == errno.EADDRINUSE:
                raise socket.error, \
                      _("Unable to bind to port %s, port already in use." % port)
            raise

        if group is not None and hasattr(os, 'getgid'):
            # if root, setgid to the running user
            if not os.getgid() and user is not None:
                try:
                    import pwd
                except ImportError:
                    raise ValueError, _("Can't change groups - no pwd module")
                try:
                    gid = pwd.getpwnam(user)[3]
                except KeyError:
                    raise ValueError,_("Group %(group)s doesn't exist")%locals()
                os.setgid(gid)
            elif os.getgid() and user is not None:
                print _('WARNING: ignoring "-g" argument, not root')

        if hasattr(os, 'getuid'):
            # if root, setuid to the running user
            if not os.getuid() and user is not None:
                try:
                    import pwd
                except ImportError:
                    raise ValueError, _("Can't change users - no pwd module")
                try:
                    uid = pwd.getpwnam(user)[2]
                except KeyError:
                    raise ValueError, _("User %(user)s doesn't exist")%locals()
                os.setuid(uid)
            elif os.getuid() and user is not None:
                print _('WARNING: ignoring "-u" argument, not root')

            # People can remove this check if they're really determined
            if not os.getuid() and user is None:
                raise ValueError, _("Can't run as root!")

        # handle tracker specs
        if args:
            d = {}
            for arg in args:
		try:
                    name, home = arg.split('=')
                except ValueError:
                    raise ValueError, _("Instances must be name=home")
                d[name] = home
            RoundupRequestHandler.TRACKER_HOMES = d
    except SystemExit:
        raise
    except ValueError:
        usage(error())
    except:
        print error()
        sys.exit(1)

    # we don't want the cgi module interpreting the command-line args ;)
    sys.argv = sys.argv[:1]

    if pidfile:
        if not hasattr(os, 'fork'):
            print "Sorry, you can't run the server as a daemon on this" \
                'Operating System'
            sys.exit(0)
        else:
            daemonize(pidfile)

    # redirect stdout/stderr to our logfile
    if logfile:
        # appending, unbuffered
        sys.stdout = sys.stderr = open(logfile, 'a', 0)

    if success_message:
        print success_message
    else:
        print _('Roundup server started on %(address)s')%locals()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print 'Keyboard Interrupt: exiting'

if __name__ == '__main__':
    run()

# vim: set filetype=python ts=4 sw=4 et si
