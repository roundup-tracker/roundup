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

$Id: roundup_server.py,v 1.11 2002-09-23 00:50:32 richard Exp $
"""

# python version check
from roundup import version_check

import sys, os, urllib, StringIO, traceback, cgi, binascii, getopt, imp
import BaseHTTPServer

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
    'bar': '/tmp/bar',
}

ROUNDUP_USER = None


# Where to log debugging information to. Use an instance of DevNull if you
# don't want to log anywhere.
# TODO: actually use this stuff
#class DevNull:
#    def write(self, info):
#        pass
#LOG = open('/var/log/roundup.cgi.log', 'a')
#LOG = DevNull()

#
##  end configuration
#


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
                self.wfile.write("<pre>")
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                self.wfile.write(cgi.escape(s.getvalue()))
                self.wfile.write("</pre>\n")
        sys.stdin = save_stdin

    do_GET = do_POST = do_HEAD = send_head = run_cgi

    def index(self):
        ''' Print up an index of the available instances
        '''
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        w = self.wfile.write
        w(_('<html><head><title>Roundup instances index</title></head>\n'))
        w(_('<body><h1>Roundup instances index</h1><ol>\n'))
        for instance in self.TRACKER_HOMES.keys():
            w(_('<li><a href="%(instance_url)s/index">%(instance_name)s</a>\n')%{
                'instance_url': urllib.quote(instance),
                'instance_name': cgi.escape(instance)})
        w(_('</ol></body></html>'))

    def inner_run_cgi(self):
        ''' This is the inner part of the CGI handling
        '''

        rest = self.path
        i = rest.rfind('?')
        if i >= 0:
            rest, query = rest[:i], rest[i+1:]
        else:
            query = ''

        # figure the instance
        if rest == '/':
            return self.index()
        l_path = rest.split('/')
        instance_name = urllib.unquote(l_path[1])
        if self.TRACKER_HOMES.has_key(instance_name):
            instance_home = self.TRACKER_HOMES[instance_name]
            instance = roundup.instance.open(instance_home)
        else:
            raise client.NotFound

        # figure out what the rest of the path is
        if len(l_path) > 2:
            rest = '/'.join(l_path[2:])
        else:
            rest = '/'

        # Set up the CGI environment
        env = {}
        env['TRACKER_NAME'] = instance_name
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
        env['HTTP_HOST'] = self.headers['host']

        decoded_query = query.replace('+', ' ')

        # do the roundup thang
        c = instance.Client(instance, self, env)
        c.main()

def usage(message=''):
    if message:
        message = _('Error: %(error)s\n\n')%{'error': message}
    print _('''%(message)sUsage:
roundup-server [-n hostname] [-p port] [-l file] [-d file] [name=instance home]*

 -n: sets the host name
 -p: sets the port to listen on
 -l: sets a filename to log to (instead of stdout)
 -d: daemonize, and write the server's PID to the nominated file

 name=instance home
   Sets the instance home(s) to use. The name is how the instance is
   identified in the URL (it's the first part of the URL path). The
   instance home is the directory that was identified when you did
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

def run():
    hostname = ''
    port = 8080
    pidfile = None
    logfile = None
    try:
        # handle the command-line args
        try:
            optlist, args = getopt.getopt(sys.argv[1:], 'n:p:u:d:l:')
        except getopt.GetoptError, e:
            usage(str(e))

        user = ROUNDUP_USER
        for (opt, arg) in optlist:
            if opt == '-n': hostname = arg
            elif opt == '-p': port = int(arg)
            elif opt == '-u': user = arg
            elif opt == '-d': pidfile = arg
            elif opt == '-l': logfile = arg
            elif opt == '-h': usage()

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

        # handle instance specs
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
    except:
        exc_type, exc_value = sys.exc_info()[:2]
        usage('%s: %s'%(exc_type, exc_value))

    # we don't want the cgi module interpreting the command-line args ;)
    sys.argv = sys.argv[:1]
    address = (hostname, port)

    # fork?
    if pidfile:
        daemonize(pidfile)

    # redirect stdout/stderr to our logfile
    if logfile:
        sys.stdout = sys.stderr = open(logfile, 'a')

    httpd = BaseHTTPServer.HTTPServer(address, RoundupRequestHandler)
    print _('Roundup server started on %(address)s')%locals()
    httpd.serve_forever()

if __name__ == '__main__':
    run()

# vim: set filetype=python ts=4 sw=4 et si
