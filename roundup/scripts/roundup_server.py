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

"""Command-line script that runs a server over roundup.cgi.client.

$Id: roundup_server.py,v 1.57 2004-07-27 00:45:49 richard Exp $
"""
__docformat__ = 'restructuredtext'

# python version check
from roundup import version_check
from roundup import __version__ as roundup_version

import sys, os, urllib, StringIO, traceback, cgi, binascii, getopt, imp
import SocketServer, BaseHTTPServer, socket, errno, ConfigParser

# Roundup modules of use here
from roundup.cgi import cgitb, client
import roundup.instance
from roundup.i18n import _

try:
    import signal
except:
    signal = None

# "default" favicon.ico
# generate by using "icotool" and tools/base64
import zlib, base64
favico = zlib.decompress(base64.decodestring('''
eJztjr1PmlEUh59XgVoshdYPWorFIhaRFq0t9pNq37b60lYSTRzcTFw6GAfj5gDYaF0dTB0MxMSE
gQQd3FzKJiEC0UCIUUN1M41pV2JCXySg/0ITn5tfzvmdc+85FwT56HSc81UJjXJsk1UsNcsSqCk1
BS64lK+vr7OyssLJyQl2ux2j0cjU1BQajYZIJEIwGMRms+H3+zEYDExOTjI2Nsbm5iZWqxWv18vW
1hZDQ0Ok02kmJiY4Ojpienqa3d1dxsfHUSqVeDwe5ufnyeVyrK6u4nK5ODs7Y3FxEYfDwdzcHCaT
icPDQ5LJJIIgMDIyQj6fZ39/n+3tbdbW1pAkiYWFBWZmZtjb2yMejzM8PEwgEMDn85HNZonFYqjV
asLhMMvLy2QyGfR6PaOjowwODmKxWDg+PkalUhEKhSgUCiwtLWE2m9nZ2UGhULCxscHp6SmpVIpo
NMrs7CwHBwdotVoSiQRXXPG/IzY7RHtt922xjFRb01H1XhKfPBNbi/7my7rrLXJ88eppvxwEfV3f
NY3Y6exofVdsV3+2wnPFDdPjB83n7xuVpcFvygPbGwxF31LZIKrQDfR2Xvh7lmrX654L/7bvlnng
bn3Zuj8M9Hepux6VfZtW1yA6K7cfGqVu8TL325u+fHTb71QKbk+7TZQ+lTc6RcnpqW8qmVQBoj/g
23eo0sr/NIGvB37K+lOWXMvJ+uWFeKGU/03Cb7n3D4M3wxI=
'''.strip()))

class RoundupRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    TRACKER_HOMES = {}
    LOG_IPADDRESS = 1

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
        except client.Unauthorised, message:
            self.send_error(403, '%s (%s)'%(self.path, message))
        except:
            exc, val, tb = sys.exc_info()
            if hasattr(socket, 'timeout') and isinstance(val, socket.timeout):
                self.log_error('timeout')
            else:
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

    do_GET = do_POST = do_HEAD = run_cgi

    def index(self):
        ''' Print up an index of the available trackers
        '''
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        w = self.wfile.write
        w(_('<html><head><title>Roundup trackers index</title></head>\n'
            '<body><h1>Roundup trackers index</h1><ol>\n'))
        keys = self.TRACKER_HOMES.keys()
        keys.sort()
        for tracker in keys:
            w('<li><a href="%(tracker_url)s/index">%(tracker_name)s</a>\n'%{
                'tracker_url': urllib.quote(tracker),
                'tracker_name': cgi.escape(tracker)})
        w('</ol></body></html>')

    def inner_run_cgi(self):
        ''' This is the inner part of the CGI handling
        '''
        rest = self.path

        if rest == '/favicon.ico':
            self.send_response(200)
            self.send_header('Content-Type', 'image/x-icon')
            self.end_headers()
            self.wfile.write(favico)
            return

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

    def address_string(self):
        if self.LOG_IPADDRESS:
            return self.client_address[0]
        else:
            host, port = self.client_address
            return socket.getfqdn(host)

    def log_message(self, format, *args):
        ''' Try to *safely* log to stderr.
        '''
        try:
            BaseHTTPServer.BaseHTTPRequestHandler.log_message(self,
                format, *args)
        except IOError:
            # stderr is no longer viable
            pass

def error():
    exc_type, exc_value = sys.exc_info()[:2]
    return _('Error: %s: %s' % (exc_type, exc_value))

# See whether we can use the forking server
if hasattr(os, 'fork'):
    class server_class(SocketServer.ForkingMixIn, BaseHTTPServer.HTTPServer):
        pass
else:
    server_class = BaseHTTPServer.HTTPServer

try:
    import win32serviceutil
except:
    RoundupService = None
else:

    # allow the win32
    import win32service
    import win32event
    from win32event import *
    from win32file import *

    SvcShutdown = "ServiceShutdown"

    class RoundupService(win32serviceutil.ServiceFramework,
            BaseHTTPServer.HTTPServer):
        ''' A Roundup standalone server for Win32 by Ewout Prangsma
        '''
        _svc_name_ = "Roundup Bug Tracker"
        _svc_display_name_ = "Roundup Bug Tracker"
        address = (HOSTNAME, PORT)
        def __init__(self, args):
            # redirect stdout/stderr to our logfile
            if LOGFILE:
                # appending, unbuffered
                sys.stdout = sys.stderr = open(LOGFILE, 'a', 0)
            win32serviceutil.ServiceFramework.__init__(self, args)
            BaseHTTPServer.HTTPServer.__init__(self, self.address,
                RoundupRequestHandler)

            # Create the necessary NT Event synchronization objects...
            # hevSvcStop is signaled when the SCM sends us a notification
            # to shutdown the service.
            self.hevSvcStop = win32event.CreateEvent(None, 0, 0, None)

            # hevConn is signaled when we have a new incomming connection.
            self.hevConn    = win32event.CreateEvent(None, 0, 0, None)

            # Hang onto this module for other people to use for logging
            # purposes.
            import servicemanager
            self.servicemanager = servicemanager

        def SvcStop(self):
            # Before we do anything, tell the SCM we are starting the
            # stop process.
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.hevSvcStop)

        def SvcDoRun(self):
            try:
                self.serve_forever()
            except SvcShutdown:
                pass

        def get_request(self):
            # Call WSAEventSelect to enable self.socket to be waited on.
            WSAEventSelect(self.socket, self.hevConn, FD_ACCEPT)
            while 1:
                try:
                    rv = self.socket.accept()
                except socket.error, why:
                    if why[0] != WSAEWOULDBLOCK:
                        raise
                    # Use WaitForMultipleObjects instead of select() because
                    # on NT select() is only good for sockets, and not general
                    # NT synchronization objects.
                    rc = WaitForMultipleObjects((self.hevSvcStop, self.hevConn),
                        0, INFINITE)
                    if rc == WAIT_OBJECT_0:
                        # self.hevSvcStop was signaled, this means:
                        # Stop the service!
                        # So we throw the shutdown exception, which gets
                        # caught by self.SvcDoRun
                        raise SvcShutdown
                    # Otherwise, rc == WAIT_OBJECT_0 + 1 which means
                    # self.hevConn was signaled, which means when we call
                    # self.socket.accept(), we'll have our incoming connection
                    # socket!
                    # Loop back to the top, and let that accept do its thing...
                else:
                    # yay! we have a connection
                    # However... the new socket is non-blocking, we need to
                    # set it back into blocking mode. (The socket that accept()
                    # returns has the same properties as the listening sockets,
                    # this includes any properties set by WSAAsyncSelect, or
                    # WSAEventSelect, and whether its a blocking socket or not.)
                    #
                    # So if you yank the following line, the setblocking() call
                    # will be useless. The socket will still be in non-blocking
                    # mode.
                    WSAEventSelect(rv[0], self.hevConn, 0)
                    rv[0].setblocking(1)
                    break
            return rv

def usage(message=''):
    if RoundupService:
        os_part = \
""''' -c <Command>  Windows Service options.
               If you want to run the server as a Windows Service, you
               must configure the rest of the options by changing the
               constants of this program.  You will at least configure
               one tracker in the TRACKER_HOMES variable.  This option
               is mutually exclusive from the rest.  Typing
               "roundup-server -c help" shows Windows Services
               specifics.'''
    else:
        os_part = ""''' -u <UID>      runs the Roundup web server as this UID
 -g <GID>      runs the Roundup web server as this GID
 -d <PIDfile>  run the server in the background and write the server's PID
               to the file indicated by PIDfile. The -l option *must* be
               specified if -d is used.'''
    port=PORT
    if message:
        message += '\n'
    print _('''%(message)sUsage: roundup-server [options] [name=tracker home]*

Options:
 -v            prints the Roundup version number and exits
 -C <fname>    use configuration file
 -n <name>     sets the host name of the Roundup web server instance
 -p <port>     sets the port to listen on (default: %(port)s)
 -l <fname>    log to the file indicated by fname instead of stderr/stdout
 -N            log client machine names instead of IP addresses (much slower)
%(os_part)s

Examples:
 roundup-server -C /opt/roundup/etc/roundup-server.ini

 roundup-server support=/var/spool/roundup-trackers/support

 roundup-server -d /var/run/roundup.pid -l /var/log/roundup.log \\
     support=/var/spool/roundup-trackers/support

Configuration file format:
   See the "admin_guide" in the Roundup "doc" directory.

How to use "name=tracker home":
   These arguments set the tracker home(s) to use. The name is how the
   tracker is identified in the URL (it's the first part of the URL path).
   The tracker home is the directory that was identified when you did
   "roundup-admin init". You may specify any number of these name=home
   pairs on the command-line. Make sure the name part doesn't include
   any url-unsafe characters like spaces, as these confuse IE.
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

def setgid(group):
    if group is None:
        return
    if not hasattr(os, 'setgid'):
        return

    # if root, setgid to the running user
    if not os.getuid():
        print _('WARNING: ignoring "-g" argument, not root')
        return

    try:
        import grp
    except ImportError:
        raise ValueError, _("Can't change groups - no grp module")
    try:
        try:
            gid = int(group)
        except ValueError:
            gid = grp.getgrnam(group)[2]
        else:
            grp.getgrgid(gid)
    except KeyError:
        raise ValueError,_("Group %(group)s doesn't exist")%locals()
    os.setgid(gid)

def setuid(user):
    if not hasattr(os, 'getuid'):
        return

    # People can remove this check if they're really determined
    if user is None:
        raise ValueError, _("Can't run as root!")

    if os.getuid():
        print _('WARNING: ignoring "-u" argument, not root')

    try:
        import pwd
    except ImportError:
        raise ValueError, _("Can't change users - no pwd module")
    try:
        try:
            uid = int(user)
        except ValueError:
            uid = pwd.getpwnam(user)[2]
        else:
            pwd.getpwuid(uid)
    except KeyError:
        raise ValueError, _("User %(user)s doesn't exist")%locals()
    os.setuid(uid)

def run(port=PORT, success_message=None):
    ''' Script entry point - handle args and figure out what to to.
    '''
    # time out after a minute if we can
    import socket
    if hasattr(socket, 'setdefaulttimeout'):
        socket.setdefaulttimeout(60)

    undefined = []
    hostname = pidfile = logfile = user = group = svc_args = log_ip = undefined
    config = None

    try:
        # handle the command-line args
        options = 'n:p:g:u:d:l:C:hNv'
        if RoundupService:
            options += 'c'

        try:
            optlist, args = getopt.getopt(sys.argv[1:], options)
        except getopt.GetoptError, e:
            usage(str(e))

        for (opt, arg) in optlist:
            if opt == '-n': hostname = arg
            elif opt == '-v':
                print '%s (python %s)'%(roundup_version, sys.version.split()[0])
                return
            elif opt == '-p': port = int(arg)
            elif opt == '-u': user = arg
            elif opt == '-g': group = arg
            elif opt == '-d': pidfile = os.path.abspath(arg)
            elif opt == '-l': logfile = os.path.abspath(arg)
            elif opt == '-h': usage()
            elif opt == '-N': log_ip = 0
            elif opt == '-c': svc_args = [opt] + args; args = None
            elif opt == '-C': config = arg

        if svc_args is not None and len(optlist) > 1:
            raise ValueError, _("windows service option must be the only one")

        if pidfile and not logfile:
            raise ValueError, _("logfile *must* be specified if pidfile is")

        # handle the config file
        if config:
            cfg = ConfigParser.ConfigParser()
            cfg.read(filename)
            if port is undefined:
                port = cfg.get('server', 'port', 8080)
            if user is undefined and cfg.has_option('server', 'user'):
                user = cfg.get('server', 'user')
            if group is undefined and cfg.has_option('server', 'group'):
                group = cfg.get('server', 'group')
            if log_ip is undefined and cfg.has_option('server', 'log_ip'):
                RoundupRequestHandler.LOG_IPADDRESS = cfg.getboolean('server',
                    'log_ip')
            if pidfile is undefined and cfg.has_option('server', 'pidfile'):
                pidfile = cfg.get('server', 'pidfile')
            if logfile is undefined and cfg.has_option('server', 'logfile'):
                logfile = cfg.get('server', 'logfile')
            homes = RoundupRequestHandler.TRACKER_HOMES
            for section in cfg.sections():
                if section == 'server':
                    continue
                homes[section] = cfg.get(section, 'home')

        # obtain server before changing user id - allows to use port <
        # 1024 if started as root
        address = (hostname, port)
        try:
            httpd = server_class(address, RoundupRequestHandler)
        except socket.error, e:
            if e[0] == errno.EADDRINUSE:
                raise socket.error, \
                      _("Unable to bind to port %s, port already in use."%port)
            raise

        # change user and/or group
        setgid(group)
        setuid(user)

        # handle tracker specs
        if args:
            for arg in args:
                try:
                    name, home = arg.split('=')
                except ValueError:
                    raise ValueError, _("Instances must be name=home")
                home = os.path.abspath(home)
                RoundupRequestHandler.TRACKER_HOMES[name] = home
    except SystemExit:
        raise
    except ValueError:
        usage(error())
    except:
        print error()
        sys.exit(1)

    # we don't want the cgi module interpreting the command-line args ;)
    sys.argv = sys.argv[:1]

    # fork the server from our parent if a pidfile is specified
    if pidfile:
        if not hasattr(os, 'fork'):
            print _("Sorry, you can't run the server as a daemon"
                " on this Operating System")
            sys.exit(0)
        else:
            daemonize(pidfile)

    if svc_args is not None:
        # don't do any other stuff
        return win32serviceutil.HandleCommandLine(RoundupService, argv=svc_args)

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

# vim: set filetype=python sts=4 sw=4 et si :
