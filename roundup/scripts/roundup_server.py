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

$Id: roundup_server.py,v 1.94 2007-09-25 04:27:12 jpend Exp $
"""
__docformat__ = 'restructuredtext'

import errno, cgi, getopt, os, socket, sys, traceback, urllib, time
import ConfigParser, BaseHTTPServer, SocketServer, StringIO

try:
    from OpenSSL import SSL
except ImportError:
    SSL = None

from time import sleep

# python version check
from roundup import configuration, version_check
from roundup import __version__ as roundup_version

# Roundup modules of use here
from roundup.cgi import cgitb, client
from roundup.cgi.PageTemplates.PageTemplate import PageTemplate
import roundup.instance
from roundup.i18n import _

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

DEFAULT_PORT = 8080

# See what types of multiprocess server are available
# Note: the order is important.  Preferred multiprocess type
#   is the last element of this list.
# "debug" means "none" + no tracker/template cache
MULTIPROCESS_TYPES = ["debug", "none"]
try:
    import thread
except ImportError:
    pass
else:
    MULTIPROCESS_TYPES.append("thread")
if hasattr(os, 'fork'):
    MULTIPROCESS_TYPES.append("fork")
DEFAULT_MULTIPROCESS = MULTIPROCESS_TYPES[-1]

def auto_ssl():
    print _('WARNING: generating temporary SSL certificate')
    import OpenSSL, time, random, sys
    pkey = OpenSSL.crypto.PKey()
    pkey.generate_key(OpenSSL.crypto.TYPE_RSA, 768)
    cert = OpenSSL.crypto.X509()
    cert.set_serial_number(random.randint(0, sys.maxint))
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(60 * 60 * 24 * 365) # one year
    cert.get_subject().CN = '*'
    cert.get_subject().O = 'Roundup Dummy Certificate'
    cert.get_issuer().CN = 'Roundup Dummy Certificate Authority'
    cert.get_issuer().O = 'Self-Signed'
    cert.set_pubkey(pkey)
    cert.sign(pkey, 'md5')
    ctx = SSL.Context(SSL.SSLv23_METHOD)
    ctx.use_privatekey(pkey)
    ctx.use_certificate(cert)

    return ctx

class SecureHTTPServer(BaseHTTPServer.HTTPServer):
    def __init__(self, server_address, HandlerClass, ssl_pem=None):
        assert SSL, "pyopenssl not installed"
        BaseHTTPServer.HTTPServer.__init__(self, server_address, HandlerClass)
        self.socket = socket.socket(self.address_family, self.socket_type)
        if ssl_pem:
            ctx = SSL.Context(SSL.SSLv23_METHOD)
            ctx.use_privatekey_file(ssl_pem)
            ctx.use_certificate_file(ssl_pem)
        else:
            ctx = auto_ssl()
        self.ssl_context = ctx
        self.socket = SSL.Connection(ctx, self.socket)
        self.server_bind()
        self.server_activate()

    def get_request(self):
        (conn, info) = self.socket.accept()
        if self.ssl_context:

            class RetryingFile(object):
                """ SSL.Connection objects can return Want__Error
                    on recv/write, meaning "try again". We'll handle
                    the try looping here """
                def __init__(self, fileobj):
                    self.__fileobj = fileobj

                def readline(self, *args):
                    """ SSL.Connection can return WantRead """
                    line = None
                    while not line:
                        try:
                            line = self.__fileobj.readline(*args)
                        except SSL.WantReadError:
                            sleep (.1)
                            line = None
                    return line

                def read(self, *args):
                    """ SSL.Connection can return WantRead """
                    while True:
                        try:
                            return self.__fileobj.read(*args)
                        except SSL.WantReadError:
                            sleep (.1)

                def __getattr__(self, attrib):
                    return getattr(self.__fileobj, attrib)

            class ConnFixer(object):
                """ wraps an SSL socket so that it implements makefile
                    which the HTTP handlers require """
                def __init__(self, conn):
                    self.__conn = conn
                def makefile(self, mode, bufsize):
                    fo = socket._fileobject(self.__conn, mode, bufsize)
                    return RetryingFile(fo)

                def __getattr__(self, attrib):
                    return getattr(self.__conn, attrib)

            conn = ConnFixer(conn)
        return (conn, info)

class RoundupRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    TRACKER_HOMES = {}
    TRACKERS = None
    LOG_IPADDRESS = 1
    DEBUG_MODE = False
    CONFIG = None

    def get_tracker(self, name):
        """Return a tracker instance for given tracker name"""
        # Note: try/except KeyError works faster that has_key() check
        #   if the key is usually found in the dictionary
        #
        # Return cached tracker instance if we have a tracker cache
        if self.TRACKERS:
            try:
                return self.TRACKERS[name]
            except KeyError:
                pass
        # No cached tracker.  Look for home path.
        try:
            tracker_home = self.TRACKER_HOMES[name]
        except KeyError:
            raise client.NotFound
        # open the instance
        tracker = roundup.instance.open(tracker_home)
        # and cache it if we have a tracker cache
        if self.TRACKERS:
            self.TRACKERS[name] = tracker
        return tracker

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
                if self.DEBUG_MODE:
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
                else:
                    # user feedback
                    self.wfile.write(cgitb.breaker())
                    ts = time.ctime()
                    self.wfile.write('''<p>%s: An error occurred. Please check
                    the server log for more infomation.</p>'''%ts)
                    # out to the logfile
                    print 'EXCEPTION AT', ts
                    traceback.print_exc()
        sys.stdin = save_stdin

    do_GET = do_POST = do_HEAD = run_cgi

    def index(self):
        ''' Print up an index of the available trackers
        '''
        keys = self.TRACKER_HOMES.keys()
        if len(keys) == 1:
            self.send_response(302)
            self.send_header('Location', urllib.quote(keys[0]) + '/index')
            self.end_headers()
        else:
            self.send_response(200)

        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        w = self.wfile.write

        if self.CONFIG and self.CONFIG['TEMPLATE']:
            template = open(self.CONFIG['TEMPLATE']).read()
            pt = PageTemplate()
            pt.write(template)
            extra = { 'trackers': self.TRACKERS,
                'nothing' : None,
                'true' : 1,
                'false' : 0,
            }
            w(pt.pt_render(extra_context=extra))
        else:
            w(_('<html><head><title>Roundup trackers index</title></head>\n'
                '<body><h1>Roundup trackers index</h1><ol>\n'))
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

        # file-like object for the favicon.ico file information
        favicon_fileobj = None

        if rest == '/favicon.ico':
            # check to see if a custom favicon was specified, and set
            # favicon_fileobj to the input file
            if self.CONFIG is not None:
                favicon_filepath = os.path.abspath(self.CONFIG['FAVICON'])

                if os.access(favicon_filepath, os.R_OK):
                    favicon_fileobj = open(favicon_filepath, 'rb')


            if favicon_fileobj is None:
                favicon_fileobj = StringIO.StringIO(favico)

            self.send_response(200)
            self.send_header('Content-Type', 'image/x-icon')
            self.end_headers()

            # this bufsize is completely arbitrary, I picked 4K because it sounded good.
            # if someone knows of a better buffer size, feel free to plug it in.
            bufsize = 4 * 1024
            Processing = True
            while Processing:
                data = favicon_fileobj.read(bufsize)
                if len(data) > 0:
                    self.wfile.write(data)
                else:
                    Processing = False

            favicon_fileobj.close()

            return

        i = rest.rfind('?')
        if i >= 0:
            rest, query = rest[:i], rest[i+1:]
        else:
            query = ''

        # no tracker - spit out the index
        if rest == '/':
            self.index()
            return

        # figure the tracker
        l_path = rest.split('/')
        tracker_name = urllib.unquote(l_path[1]).lower()

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
        if os.environ.has_key('CGI_SHOW_TIMING'):
            env['CGI_SHOW_TIMING'] = os.environ['CGI_SHOW_TIMING']
        env['HTTP_ACCEPT_LANGUAGE'] = self.headers.get('accept-language')

        # do the roundup thing
        tracker = self.get_tracker(tracker_name)
        tracker.Client(tracker, self, env).main()

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

    def start_response(self, headers, response):
        self.send_response(response)
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()

def error():
    exc_type, exc_value = sys.exc_info()[:2]
    return _('Error: %s: %s' % (exc_type, exc_value))

def setgid(group):
    if group is None:
        return
    if not hasattr(os, 'setgid'):
        return

    # if root, setgid to the running user
    if os.getuid():
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
        if os.getuid():
            return
        raise ValueError, _("Can't run as root!")

    if os.getuid():
        print _('WARNING: ignoring "-u" argument, not root')
        return

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

class TrackerHomeOption(configuration.FilePathOption):

    # Tracker homes do not need any description strings
    def format(self):
        return "%(name)s = %(value)s\n" % {
                "name": self.setting,
                "value": self.value2str(self._value),
            }

class ServerConfig(configuration.Config):

    SETTINGS = (
            ("main", (
            (configuration.Option, "host", "",
                "Host name of the Roundup web server instance.\n"
                "If empty, listen on all network interfaces."),
            (configuration.IntegerNumberOption, "port", DEFAULT_PORT,
                "Port to listen on."),
            (configuration.NullableFilePathOption, "favicon", "favicon.ico",
                "Path to favicon.ico image file."
                "  If unset, built-in favicon.ico is used."),
            (configuration.NullableOption, "user", "",
                "User ID as which the server will answer requests.\n"
                "In order to use this option, "
                "the server must be run initially as root.\n"
                "Availability: Unix."),
            (configuration.NullableOption, "group", "",
                "Group ID as which the server will answer requests.\n"
                "In order to use this option, "
                "the server must be run initially as root.\n"
                "Availability: Unix."),
            (configuration.BooleanOption, "nodaemon", "no",
                "don't fork (this overrides the pidfile mechanism)'"),
            (configuration.BooleanOption, "log_hostnames", "no",
                "Log client machine names instead of IP addresses "
                "(much slower)"),
            (configuration.NullableFilePathOption, "pidfile", "",
                "File to which the server records "
                "the process id of the daemon.\n"
                "If this option is not set, "
                "the server will run in foreground\n"),
            (configuration.NullableFilePathOption, "logfile", "",
                "Log file path.  If unset, log to stderr."),
            (configuration.Option, "multiprocess", DEFAULT_MULTIPROCESS,
                "Set processing of each request in separate subprocess.\n"
                "Allowed values: %s." % ", ".join(MULTIPROCESS_TYPES)),
            (configuration.NullableFilePathOption, "template", "",
                "Tracker index template. If unset, built-in will be used."),
            (configuration.BooleanOption, "ssl", "no",
                "Enable SSL support (requires pyopenssl)"),
            (configuration.NullableFilePathOption, "pem", "",
                "PEM file used for SSL. A temporary self-signed certificate\n"
                "will be used if left blank."),
        )),
        ("trackers", (), "Roundup trackers to serve.\n"
            "Each option in this section defines single Roundup tracker.\n"
            "Option name identifies the tracker and will appear in the URL.\n"
            "Option value is tracker home directory path.\n"
            "The path may be either absolute or relative\n"
            "to the directory containig this config file."),
    )

    # options recognized by config
    OPTIONS = {
        "host": "n:",
        "port": "p:",
        "group": "g:",
        "user": "u:",
        "logfile": "l:",
        "pidfile": "d:",
        "nodaemon": "D",
        "log_hostnames": "N",
        "multiprocess": "t:",
        "template": "i:",
        "ssl": "s",
        "pem": "e:",
    }

    def __init__(self, config_file=None):
        configuration.Config.__init__(self, config_file, self.SETTINGS)
        self.sections.append("trackers")

    def _adjust_options(self, config):
        """Add options for tracker homes"""
        # return early if there are no tracker definitions.
        # trackers must be specified on the command line.
        if not config.has_section("trackers"):
            return
        # config defaults appear in all sections.
        # filter them out.
        defaults = config.defaults().keys()
        for name in config.options("trackers"):
            if name not in defaults:
                self.add_option(TrackerHomeOption(self, "trackers", name))

    def getopt(self, args, short_options="", long_options=(),
        config_load_options=("C", "config"), **options
    ):
        options.update(self.OPTIONS)
        return configuration.Config.getopt(self, args,
            short_options, long_options, config_load_options, **options)

    def _get_name(self):
        return "Roundup server"

    def trackers(self):
        """Return tracker definitions as a list of (name, home) pairs"""
        trackers = []
        for option in self._get_section_options("trackers"):
            trackers.append((option, os.path.abspath(
                self["TRACKERS_" + option.upper()])))
        return trackers

    def set_logging(self):
        """Initialise logging to the configured file, if any."""
        # appending, unbuffered
        sys.stdout = sys.stderr = open(self["LOGFILE"], 'a', 0)

    def get_server(self):
        """Return HTTP server object to run"""
        # we don't want the cgi module interpreting the command-line args ;)
        sys.argv = sys.argv[:1]

        # preload all trackers unless we are in "debug" mode
        tracker_homes = self.trackers()
        if self["MULTIPROCESS"] == "debug":
            trackers = None
        else:
            trackers = dict([(name, roundup.instance.open(home, optimize=1))
                for (name, home) in tracker_homes])

        # build customized request handler class
        class RequestHandler(RoundupRequestHandler):
            LOG_IPADDRESS = not self["LOG_HOSTNAMES"]
            TRACKER_HOMES = dict(tracker_homes)
            TRACKERS = trackers
            DEBUG_MODE = self["MULTIPROCESS"] == "debug"
            CONFIG = self

        if self["SSL"]:
            base_server = SecureHTTPServer
        else:
            base_server = BaseHTTPServer.HTTPServer

        # obtain request server class
        if self["MULTIPROCESS"] not in MULTIPROCESS_TYPES:
            print _("Multiprocess mode \"%s\" is not available, "
                "switching to single-process") % self["MULTIPROCESS"]
            self["MULTIPROCESS"] = "none"
            server_class = base_server
        elif self["MULTIPROCESS"] == "fork":
            class ForkingServer(SocketServer.ForkingMixIn,
                base_server):
                    pass
            server_class = ForkingServer
        elif self["MULTIPROCESS"] == "thread":
            class ThreadingServer(SocketServer.ThreadingMixIn,
                base_server):
                    pass
            server_class = ThreadingServer
        else:
            server_class = base_server

        # obtain server before changing user id - allows to
        # use port < 1024 if started as root
        try:
            args = ((self["HOST"], self["PORT"]), RequestHandler)
            kwargs = {}
            if self["SSL"]:
                kwargs['ssl_pem'] = self["PEM"]
            httpd = server_class(*args, **kwargs)
        except socket.error, e:
            if e[0] == errno.EADDRINUSE:
                raise socket.error, \
                    _("Unable to bind to port %s, port already in use.") \
                    % self["PORT"]
            raise
        # change user and/or group
        setgid(self["GROUP"])
        setuid(self["USER"])
        # return the server
        return httpd

try:
    import win32serviceutil
except:
    RoundupService = None
else:

    # allow the win32
    import win32service

    class SvcShutdown(Exception):
        pass

    class RoundupService(win32serviceutil.ServiceFramework):

        _svc_name_ = "roundup"
        _svc_display_name_ = "Roundup Bug Tracker"

        running = 0
        server = None

        def SvcDoRun(self):
            import servicemanager
            self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
            config = ServerConfig()
            (optlist, args) = config.getopt(sys.argv[1:])
            if not config["LOGFILE"]:
                servicemanager.LogMsg(servicemanager.EVENTLOG_ERROR_TYPE,
                    servicemanager.PYS_SERVICE_STOPPED,
                    (self._svc_display_name_, "\r\nMissing logfile option"))
                self.ReportServiceStatus(win32service.SERVICE_STOPPED)
                return
            config.set_logging()
            self.server = config.get_server()
            self.running = 1
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED, (self._svc_display_name_,
                    " at %s:%s" % (config["HOST"], config["PORT"])))
            while self.running:
                self.server.handle_request()
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_display_name_, ""))
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)

        def SvcStop(self):
            self.running = 0
            # make dummy connection to self to terminate blocking accept()
            addr = self.server.socket.getsockname()
            if addr[0] == "0.0.0.0":
                addr = ("127.0.0.1", addr[1])
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(addr)
            sock.close()
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)

def usage(message=''):
    if RoundupService:
        os_part = \
""''' -c <Command>  Windows Service options.
               If you want to run the server as a Windows Service, you
               must use configuration file to specify tracker homes.
               Logfile option is required to run Roundup Tracker service.
               Typing "roundup-server -c help" shows Windows Services
               specifics.'''
    else:
        os_part = ""''' -u <UID>      runs the Roundup web server as this UID
 -g <GID>      runs the Roundup web server as this GID
 -d <PIDfile>  run the server in the background and write the server's PID
               to the file indicated by PIDfile. The -l option *must* be
               specified if -d is used.'''
    if message:
        message += '\n'
    print _('''%(message)sUsage: roundup-server [options] [name=tracker home]*

Options:
 -v            print the Roundup version number and exit
 -h            print this text and exit
 -S            create or update configuration file and exit
 -C <fname>    use configuration file <fname>
 -n <name>     set the host name of the Roundup web server instance
 -p <port>     set the port to listen on (default: %(port)s)
 -l <fname>    log to the file indicated by fname instead of stderr/stdout
 -N            log client machine names instead of IP addresses (much slower)
 -i <fname>    set tracker index template
 -s            enable SSL
 -e <fname>    PEM file containing SSL key and certificate
 -t <mode>     multiprocess mode (default: %(mp_def)s).
               Allowed values: %(mp_types)s.
%(os_part)s

Long options:
 --version          print the Roundup version number and exit
 --help             print this text and exit
 --save-config      create or update configuration file and exit
 --config <fname>   use configuration file <fname>
 All settings of the [main] section of the configuration file
 also may be specified in form --<name>=<value>

Examples:

 roundup-server -S -C /opt/roundup/etc/roundup-server.ini \\
    -n localhost -p 8917 -l /var/log/roundup.log \\
    support=/var/spool/roundup-trackers/support

 roundup-server -C /opt/roundup/etc/roundup-server.ini

 roundup-server support=/var/spool/roundup-trackers/support

 roundup-server -d /var/run/roundup.pid -l /var/log/roundup.log \\
    support=/var/spool/roundup-trackers/support

Configuration file format:
   Roundup Server configuration file has common .ini file format.
   Configuration file created with 'roundup-server -S' contains
   detailed explanations for each option.  Please see that file
   for option descriptions.

How to use "name=tracker home":
   These arguments set the tracker home(s) to use. The name is how the
   tracker is identified in the URL (it's the first part of the URL path).
   The tracker home is the directory that was identified when you did
   "roundup-admin init". You may specify any number of these name=home
   pairs on the command-line. Make sure the name part doesn't include
   any url-unsafe characters like spaces, as these confuse IE.
''') % {
    "message": message,
    "os_part": os_part,
    "port": DEFAULT_PORT,
    "mp_def": DEFAULT_MULTIPROCESS,
    "mp_types": ", ".join(MULTIPROCESS_TYPES),
}


def writepidfile(pidfile):
    ''' Write a pidfile (only). Do not daemonize. '''
    pid = os.getpid()
    if pid:
        pidfile = open(pidfile, 'w')
        pidfile.write(str(pid))
        pidfile.close()

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

    # close off std(in|out|err), redirect to devnull so the file
    # descriptors can't be used again
    devnull = os.open('/dev/null', 0)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)

undefined = []
def run(port=undefined, success_message=None):
    ''' Script entry point - handle args and figure out what to to.
    '''
    # time out after a minute if we can
    if hasattr(socket, 'setdefaulttimeout'):
        socket.setdefaulttimeout(60)

    config = ServerConfig()
    # additional options
    short_options = "hvS"
    if RoundupService:
        short_options += 'c'
    try:
        (optlist, args) = config.getopt(sys.argv[1:],
            short_options, ("help", "version", "save-config",))
    except (getopt.GetoptError, configuration.ConfigurationError), e:
        usage(str(e))
        return

    # if running in windows service mode, don't do any other stuff
    if ("-c", "") in optlist:
        # acquire command line options recognized by service
        short_options = "cC:"
        long_options = ["config"]
        for (long_name, short_name) in config.OPTIONS.items():
            short_options += short_name
            long_name = long_name.lower().replace("_", "-")
            if short_name[-1] == ":":
                long_name += "="
            long_options.append(long_name)
        optlist = getopt.getopt(sys.argv[1:], short_options, long_options)[0]
        svc_args = []
        for (opt, arg) in optlist:
            if opt in ("-C", "-l"):
                # make sure file name is absolute
                svc_args.extend((opt, os.path.abspath(arg)))
            elif opt in ("--config", "--logfile"):
                # ditto, for long options
                svc_args.append("=".join(opt, os.path.abspath(arg)))
            elif opt != "-c":
                svc_args.extend(opt)
        RoundupService._exe_args_ = " ".join(svc_args)
        # pass the control to serviceutil
        win32serviceutil.HandleCommandLine(RoundupService,
            argv=sys.argv[:1] + args)
        return

    # add tracker names from command line.
    # this is done early to let '--save-config' handle the trackers.
    if args:
        for arg in args:
            try:
                name, home = arg.split('=')
            except ValueError:
                raise ValueError, _("Instances must be name=home")
            config.add_option(TrackerHomeOption(config, "trackers", name))
            config["TRACKERS_" + name.upper()] = home

    # handle remaining options
    if optlist:
        for (opt, arg) in optlist:
            if opt in ("-h", "--help"):
                usage()
            elif opt in ("-v", "--version"):
                print '%s (python %s)' % (roundup_version,
                    sys.version.split()[0])
            elif opt in ("-S", "--save-config"):
                config.save()
                print _("Configuration saved to %s") % config.filepath
        # any of the above options prevent server from running
        return

    # port number in function arguments overrides config and command line
    if port is not undefined:
        config.PORT = port

    if config["LOGFILE"]:
        config["LOGFILE"] = os.path.abspath(config["LOGFILE"])
        # switch logging from stderr/stdout to logfile
        config.set_logging()
    if config["PIDFILE"]:
        config["PIDFILE"] = os.path.abspath(config["PIDFILE"])

    # fork the server from our parent if a pidfile is specified
    if config["PIDFILE"]:
        if not hasattr(os, 'fork'):
            print _("Sorry, you can't run the server as a daemon"
                " on this Operating System")
            sys.exit(0)
        else:
            if config['NODAEMON']:
                writepidfile(config["PIDFILE"])
            else:
                daemonize(config["PIDFILE"])

    # create the server
    httpd = config.get_server()

    if success_message:
        print success_message
    else:
        print _('Roundup server started on %(HOST)s:%(PORT)s') \
            % config

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print 'Keyboard Interrupt: exiting'

if __name__ == '__main__':
    run()

# vim: sts=4 sw=4 et si
