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
"""
from __future__ import print_function
__docformat__ = 'restructuredtext'

import base64   # decode icon
import errno
import getopt
import io
import logging
import os
import re
import socket
import sys     # modify sys.path when running in source tree
import time
import traceback
import zlib    # decompress icon

try:
    # Python 3.
    import socketserver
except ImportError:
    # Python 2.
    import SocketServer as socketserver

try:
    # Python 2.
    reload
except NameError:
    # Python 3.
    from importlib import reload

try:
    from OpenSSL import SSL
except ImportError:
    SSL = None

# --- patch sys.path to make sure 'import roundup' finds correct version
import os.path as osp

thisdir = osp.dirname(osp.abspath(__file__))
rootdir = osp.dirname(osp.dirname(thisdir))
if (osp.exists(thisdir + '/__init__.py') and
        osp.exists(rootdir + '/roundup/__init__.py')):
    # the script is located inside roundup source code
    sys.path.insert(0, rootdir)
# --/

import roundup.instance                                        # noqa: E402

# python version_check raises exception if imported for wrong python version
from roundup import configuration, version_check           # noqa: F401,E402
from roundup import __version__ as roundup_version         # noqa: E402
# Roundup modules of use here
from roundup.anypy import http_, urllib_                   # noqa: E402
from roundup.anypy.html import html_escape                 # noqa: E402
from roundup.anypy.strings import s2b, StringIO            # noqa: E402
from roundup.cgi import cgitb, client                      # noqa: E402
from roundup.cgi.PageTemplates.PageTemplate import PageTemplate  # noqa: E402
from roundup.i18n import _                                 # noqa: E402

# "default" favicon.ico
# generate by using "icotool" and tools/base64
favico = zlib.decompress(base64.b64decode(b'''
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
    import threading  # noqa: F401
except ImportError:
    pass
else:
    MULTIPROCESS_TYPES.append("thread")
if hasattr(os, 'fork'):
    MULTIPROCESS_TYPES.append("fork")
DEFAULT_MULTIPROCESS = MULTIPROCESS_TYPES[-1]


def auto_ssl():
    print(_('WARNING: generating temporary SSL certificate'))
    import OpenSSL, random                               # noqa: E401
    pkey = OpenSSL.crypto.PKey()
    pkey.generate_key(OpenSSL.crypto.TYPE_RSA, 2048)
    cert = OpenSSL.crypto.X509()
    cert.set_serial_number(random.randint(0, sys.maxsize))
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(60 * 60 * 24 * 365)  # one year
    cert.get_subject().CN = '*'
    cert.get_subject().O = 'Roundup Dummy Certificate'            # noqa: E741
    cert.get_issuer().CN = 'Roundup Dummy Certificate Authority'
    cert.get_issuer().O = 'Self-Signed'                           # noqa: E741
    cert.set_pubkey(pkey)
    cert.sign(pkey, 'sha512')
    ctx = SSL.Context(OpenSSL.SSL.TLSv1_2_METHOD)
    ctx.use_privatekey(pkey)
    ctx.use_certificate(cert)

    return ctx


class SecureHTTPServer(http_.server.HTTPServer):
    def __init__(self, server_address, HandlerClass, ssl_pem=None):
        assert SSL, "pyopenssl not installed"
        http_.server.HTTPServer.__init__(self, server_address, HandlerClass)
        self.socket = socket.socket(self.address_family, self.socket_type)
        if ssl_pem:
            ctx = SSL.Context(SSL.TLSv1_2_METHOD)
            try:
                ctx.use_privatekey_file(ssl_pem)
            except SSL.Error:
                print(_("Unable to find/use key from file: %(pemfile)s") % {"pemfile": ssl_pem})
                print(_("Does it have a private key surrounded by '-----BEGIN PRIVATE KEY-----' and\n  '-----END PRIVATE KEY-----' markers?"))
                exit()
            try:
                ctx.use_certificate_file(ssl_pem)
            except SSL.Error:
                print(_("Unable to find/use certificate from file: %(pemfile)s") % {"pemfile": ssl_pem})
                print(_("Does it have a certificate surrounded by '-----BEGIN CERTIFICATE-----' and\n  '-----END CERTIFICATE-----' markers?"))
                exit()
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
                    while True:
                        try:
                            return self.__fileobj.readline(*args)
                        except SSL.WantReadError:
                            time.sleep(.1)
                        except SSL.ZeroReturnError:
                            # Raised here on every request.
                            # SSL connection has been closed.
                            # But maybe not the underlying socket.
                            # FIXME: Does this lead to a socket leak??
                            #  if so how to fix?
                            pass

                def read(self, *args):
                    """ SSL.Connection can return WantRead """
                    while True:
                        try:
                            return self.__fileobj.read(*args)
                        except SSL.WantReadError:
                            time.sleep(.1)
                        except SSL.ZeroReturnError:
                            # Put here to match readline() handling above.
                            # Even though this never was the source of the
                            #  exception logged during use.
                            # SSL connection has been closed.
                            # But maybe not the underlying socket.
                            # FIXME: Does this lead to a socket leak??
                            #  if so how to fix?
                            pass

                def __getattr__(self, attrib):
                    return getattr(self.__fileobj, attrib)

            class ConnFixer(object):
                """ wraps an SSL socket so that it implements makefile
                    which the HTTP handlers require """
                def __init__(self, conn):
                    self.__conn = conn

                def makefile(self, mode, bufsize):
                    fo = None
                    try:
                        # see below of url used for this
                        fo = socket.SocketIO(self.__conn, mode)
                    except AttributeError:
                        # python 2 in use
                        buffer = socket._fileobject(self.__conn, mode, bufsize)

                    if fo:
                        # python3 set up buffering
                        # verify mode is rb and bufsize is -1
                        # implement subset of socket::makefile
                        # https://bugs.launchpad.net/python-glanceclient/+bug/1812525
                        if mode == 'rb' and bufsize == -1:
                            buffering = io.DEFAULT_BUFFER_SIZE
                            buffer = io.BufferedReader(fo, buffering)
                        else:
                            buffer = fo

                    return RetryingFile(buffer)

                def __getattr__(self, attrib):
                    return getattr(self.__conn, attrib)

            conn = ConnFixer(conn)
        return (conn, info)


class RoundupRequestHandler(http_.server.BaseHTTPRequestHandler):
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
        try:
            self.inner_run_cgi()
        except client.NotFound:
            self.send_error(404, self.path)
        except client.Unauthorised as message:
            self.send_error(403, '%s (%s)' % (self.path, message))
        except Exception:
            exc, val, tb = sys.exc_info()
            if hasattr(socket, 'timeout') and isinstance(val, socket.timeout):
                self.log_error('timeout')
                self.send_response(408)
                self.send_header('Content-Type', 'text/html')

                output = s2b('''<body><p>Connection timed out</p></body>''')
                # Close connection
                self.send_header('Content-Length', len(output))
                self.end_headers()
                self.wfile.write(output)
                self.close_connection = True
            else:
                self.send_response(400)
                self.send_header('Content-Type', 'text/html')
                if self.DEBUG_MODE:
                    try:
                        reload(cgitb)
                        output = s2b(cgitb.breaker()) + s2b(cgitb.html())
                    except Exception:
                        s = StringIO()
                        traceback.print_exc(None, s)
                        output = b"<pre>%s</pre>" % s2b(
                            html_escape(s.getvalue()))
                else:
                    # user feedback
                    ts = time.ctime()
                    output = (
                        s2b('''<body><p>%s: An error occurred. Please check
                        the server log for more information.</p></body>''' %
                            ts)
                    )
                    # out to the logfile
                    print('EXCEPTION AT', ts)
                    traceback.print_exc()

                # complete output to user.
                self.send_header('Content-Length', len(output))
                self.end_headers()
                self.wfile.write(output)

    do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = \
        do_PATCH = do_OPTIONS = run_cgi

    def index(self):
        ''' Print up an index of the available trackers
        '''
        keys = list(self.TRACKER_HOMES.keys())
        if len(keys) == 1:
            self.send_response(302)
            self.send_header('Location', urllib_.quote(keys[0]) + '/index')
            self.send_header('Content-Length', 0)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        output = []

        w = self.wfile.write

        if self.CONFIG and self.CONFIG['TEMPLATE']:
            template = open(self.CONFIG['TEMPLATE']).read()
            pt = PageTemplate()
            pt.write(template)
            extra = {'trackers': self.TRACKERS,
                     'nothing': None,
                     'true': 1,
                     'false': 0}
            output.append(s2b(pt.pt_render(extra_context=extra)))
        else:
            output.append(s2b(_(
                '<html><head><title>Roundup trackers index</title></head>\n'
                '<body><h1>Roundup trackers index</h1><ol>\n')))
            keys.sort()
            for tracker in keys:
                output.append(s2b('<li><a href="%(tracker_url)s/index">%(tracker_name)s</a>\n' % {
                    'tracker_url': urllib_.quote(tracker),
                    'tracker_name': html_escape(tracker)}))
            output.append(b'</ol></body></html>\n')

        write_output = b"\n".join(output)
        self.send_header('Content-Length', len(write_output))
        self.end_headers()
        w(write_output)

    def inner_run_cgi(self):
        ''' This is the inner part of the CGI handling
        '''

        # self.path is /some/path?with&all=stuff
        if self.path == '/favicon.ico':
            # file-like object for the favicon.ico file information
            favicon_fileobj = None

            # check to see if a custom favicon was specified, and set
            # favicon_fileobj to the input file
            if self.CONFIG is not None:
                favicon_filepath = os.path.abspath(self.CONFIG['FAVICON'])

                if os.access(favicon_filepath, os.R_OK):
                    favicon_fileobj = open(favicon_filepath, 'rb')

            if favicon_fileobj is None:
                favicon_fileobj = io.BytesIO(favico)

            self.send_response(200)
            self.send_header('Content-Type', 'image/x-icon')
            self.send_header('Content-Length', len(favico))
            self.send_header('Cache-Control', "public, max-age=86400")
            self.end_headers()

            # this bufsize is completely arbitrary, I picked 4K because
            # it sounded good. if someone knows of a better buffer size,
            # feel free to plug it in.
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

        i = self.path.find('?')
        if i >= 0:
            # rest starts with /, query is without ?
            rest, query = self.path[:i], self.path[i+1:]
        else:
            rest = self.path
            query = ''

        # no tracker - spit out the index
        if rest == '/':
            self.index()
            return

        # figure the tracker
        l_path = rest.split('/')
        tracker_name = urllib_.unquote(l_path[1]).lower()

        # handle missing trailing '/'
        if len(l_path) == 2:
            self.send_response(301)
            # redirect - XXX https??
            protocol = 'http'
            url = '%s://%s%s/' % (protocol, self.headers['host'], rest)
            if query:
                url += '?' + query

            # Do not allow literal \n or \r in URL to prevent
            # HTTP Response Splitting
            url = re.sub("[\r\n]", "", url)
            self.send_header('Location', url)
            self.send_header('Content-Length', 17)
            self.end_headers()
            self.wfile.write(b'Moved Permanently')
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
        env['PATH_INFO'] = urllib_.unquote(rest)
        if query:
            env['QUERY_STRING'] = query
        if hasattr(self.headers, 'get_content_type'):
            # Python 3.  We need the raw header contents.
            content_type = self.headers.get('content-type')
        elif self.headers.typeheader is None:
            # Python 2.
            content_type = self.headers.type
        else:
            # Python 2.
            content_type = self.headers.typeheader
        if content_type:
            env['CONTENT_TYPE'] = content_type
        length = self.headers.get('content-length')
        if length:
            env['CONTENT_LENGTH'] = length
        if hasattr(self.headers, 'get_all'):
            # Python 3.
            ch = self.headers.get_all('cookie', [])
        else:
            # Python 2.
            ch = self.headers.getheaders('cookie')
        co = list(filter(None, ch))
        if co:
            env['HTTP_COOKIE'] = ', '.join(co)
        env['HTTP_AUTHORIZATION'] = self.headers.get('authorization')
        # self.CONFIG['INCLUDE_HEADERS'] is a list.
        for h in self.CONFIG['INCLUDE_HEADERS']:
            env[h] = self.headers.get(h, None)
            # if header is MISSING
            if env[h] is None:
                del (env[h])
        env['SCRIPT_NAME'] = ''
        env['SERVER_NAME'] = self.server.server_name
        env['SERVER_PORT'] = str(self.server.server_port)
        try:
            env['HTTP_HOST'] = self.headers['host']
        except KeyError:
            env['HTTP_HOST'] = ''
        # https://tools.ietf.org/html/draft-ietf-appsawg-http-forwarded-10
        # headers.
        xfh = self.headers.get('X-Forwarded-Host', None)
        if xfh:
            # If behind a proxy, this is the hostname supplied
            # via the Host header to the proxy. Used by core code.
            # Controlled by the CSRF settings.
            env['HTTP_X_FORWARDED_HOST'] = xfh
        xff = self.headers.get('X-Forwarded-For', None)
        if xff:
            # xff is a list of ip addresses for original client/proxies:
            # X-Forwarded-For: clientIP, proxy1IP, proxy2IP
            # May not be trustworthy. Do not use in core without
            # config option to control its use.
            # Made available for extensions if the user trusts it.
            # E.g. you may wish to disable recaptcha validation extension
            # if the ip of the client matches 198.51.100.X
            env['HTTP_X_FORWARDED_FOR'] = xff
        xfp = self.headers.get('X-Forwarded-Proto', None)
        if xfp:
            # xfp is the protocol (http/https) seen by proxies in the
            # path of the request. I am not sure if there is only
            # one value or multiple, but I suspect multiple
            # is possible so:
            # X-Forwarded-Proto: https, http
            # is expected if the path is:
            #    client -> proxy1 -> proxy2 -> back end server
            # an proxy1 is an SSL terminator.
            # May not be trustworthy. Do not use in core without
            # config option to control its use.
            # Made available for extensions if the user trusts it.
            env['HTTP_X_FORWARDED_PROTO'] = xfp
        if 'CGI_SHOW_TIMING' in os.environ:
            env['CGI_SHOW_TIMING'] = os.environ['CGI_SHOW_TIMING']
        env['HTTP_ACCEPT_LANGUAGE'] = self.headers.get('accept-language')
        referer = self.headers.get('Referer')
        if referer:
            env['HTTP_REFERER'] = referer
        origin = self.headers.get('Origin')
        if origin:
            env['HTTP_ORIGIN'] = origin
        xrw = self.headers.get('x-requested-with')
        if xrw:
            env['HTTP_X_REQUESTED_WITH'] = xrw
        range = self.headers.get('range')
        if range:
            env['HTTP_RANGE'] = range
        if_range = self.headers.get('if-range')
        if range:
            env['HTTP_IF_RANGE'] = if_range

        # do the roundup thing
        tracker = self.get_tracker(tracker_name)
        tracker.Client(tracker, self, env).main()

    def address_string(self):
        """Get IP address of client from:
               left most element of X-Forwarded-For header element if set
               client ip address otherwise.
           if returned string is from X-Forwarded-For append + to string.
        """
        from_forwarded_header=""
        forwarded_for = None

        # if connection timed out, there is no headers property
        if hasattr(self, 'headers') and ('X-FORWARDED-FOR' in self.headers):
            forwarded_for = re.split(r'[,\s]',
                                     self.headers['X-FORWARDED-FOR'],
                                     maxsplit=1)[0]
            from_forwarded_header="+"
        if self.LOG_IPADDRESS:
            return "%s%s" % (forwarded_for or self.client_address[0],
                             from_forwarded_header)
        else:
            if forwarded_for:
                host = forwarded_for
            else:
                host, port = self.client_address
            return "%s%s" % (socket.getfqdn(host), from_forwarded_header)

    def log_message(self, format, *args):
        ''' Try to *safely* log to stderr.
        '''
        if self.CONFIG['LOGHTTPVIALOGGER']:
            logger = logging.getLogger('roundup.http')

            logger.info("%s - - [%s] %s" %
                        (self.address_string(),
                         self.log_date_time_string(),
                         format % args))
        else:
            try:
                http_.server.BaseHTTPRequestHandler.log_message(self,
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
    return _('Error: %(type)s: %(value)s') % {'type': exc_type,
                                             'value': exc_value}


def setgid(group):
    if group is None:
        return
    if not hasattr(os, 'setgid'):
        return

    # if root, setgid to the running user
    if os.getuid():
        print(_('WARNING: ignoring "-g" argument, not root'))
        return

    try:
        import grp
    except ImportError:
        raise ValueError(_("Can't change groups - no grp module"))
    try:
        try:
            gid = int(group)
        except ValueError:
            gid = grp.getgrnam(group)[2]
        else:
            grp.getgrgid(gid)
    except KeyError:
        raise ValueError(_("Group %(group)s doesn't exist") % locals())
    os.setgid(gid)


def setuid(user):
    if not hasattr(os, 'getuid'):
        return

    # People can remove this check if they're really determined
    if user is None:
        if os.getuid():
            return
        raise ValueError(_("Can't run as root!"))

    if os.getuid():
        print(_('WARNING: ignoring "-u" argument, not root'))
        return

    try:
        import pwd
    except ImportError:
        raise ValueError(_("Can't change users - no pwd module"))
    try:
        try:
            uid = int(user)
        except ValueError:
            uid = pwd.getpwnam(user)[2]
        else:
            pwd.getpwuid(uid)
    except KeyError:
        raise ValueError(_("User %(user)s doesn't exist") % locals())
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
            (configuration.Option, "host", "localhost",
                "Host name of the Roundup web server instance.\n"
                "If left unconfigured (no 'host' setting) the default\n"
                "will be used.\n"
                "If empty, listen on all network interfaces.\n"
                "If you want to explicitly listen on all\n"
                "network interfaces, the address 0.0.0.0 is a more\n"
                "explicit way to achieve this, the use of an empty\n"
                "string for this purpose is deprecated and will go away\n"
                "in a future release."),
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
            (configuration.IntegerNumberOption, "max_children", 40,
                "Maximum number of children to spawn using fork "
                "multiprocess mode."),
            (configuration.BooleanOption, "nodaemon", "no",
                "don't fork (this overrides the pidfile mechanism)'"),
            (configuration.BooleanOption, "log_hostnames", "no",
                "Log client machine names instead of IP addresses "
                "(much slower)"),
            (configuration.BooleanOption, "loghttpvialogger", "no",
                "Have http(s) request logging done via python logger module.\n"
                "If set to yes the python logging module is used with "
                "qualname\n'roundup.http'. Otherwise logging is done to "
                "stderr or the file\nspecified using the -l/logfile option."),
            (configuration.BooleanOption, "log_proxy_header", "no",
                "Use first element of reverse proxy header X-Forwarded-For\n"
                "as client IP address. This appends a '+' sign to the logged\n"
                "host ip/name. Use only if server is accessible only via\n"
                "trusted reverse proxy."),
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
                "PEM file used for SSL. The PEM file must include\n"
                "both the private key and certificate with appropriate\n"
                'headers (i.e. "-----BEGIN PRIVATE KEY-----",\n'
                '"-----END PRIVATE KEY-----" and '
                '"-----BEGIN CERTIFICATE-----",\n'
                '"-----END CERTIFICATE-----". A temporary self-signed\n'
                "certificate will be used if left blank."),
            (configuration.WordListOption, "include_headers", "",
                "Comma separated list of extra headers that should\n"
                "be copied into the CGI environment.\n"
                "E.G. if you want to access the REMOTE_USER and\n"
                "X-Proxy-User headers in the back end,\n"
                "set to the value REMOTE_USER,X-Proxy-User."),
            (configuration.HttpVersionOption, "http_version", "HTTP/1.1",
                "Change to HTTP/1.0 if needed. This disables keepalive."),

        )),
        ("trackers", (), "Roundup trackers to serve.\n"
            "Each option in this section defines single Roundup tracker.\n"
            "Option name identifies the tracker and will appear in the URL.\n"
            "Option value is tracker home directory path.\n"
            "The path may be either absolute or relative\n"
            "to the directory containing this config file."),
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
        "max_children": "m:",
        "multiprocess": "t:",
        "template": "i:",
        "loghttpvialogger": 'L',
        "log_proxy_header": 'P',
        "ssl": "s",
        "pem": "e:",
        "include_headers": "I:",
        "http_version": 'V:',
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
        defaults = list(config.defaults().keys())
        for name in config.options("trackers"):
            if name not in defaults:
                self.add_option(TrackerHomeOption(self, "trackers", name))

    def getopt(self, args, short_options="", long_options=(),
               config_load_options=("C", "config"), **options):
        options.update(self.OPTIONS)
        return configuration.Config.getopt(
            self, args, short_options, long_options,
            config_load_options, **options)

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
        # appending, line-buffered (Python 3 does not allow unbuffered
        # text files)
        sys.stdout = sys.stderr = open(self["LOGFILE"], 'a', 1)

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

            def setup(self):
                if self.CONFIG["SSL"]:
                    # perform initial ssl handshake. This will set
                    # internal state correctly so that later closing SSL
                    # socket works (with SSL end-handshake started)
                    self.request.do_handshake()
                RoundupRequestHandler.protocol_version = \
                    self.CONFIG["HTTP_VERSION"]
                RoundupRequestHandler.setup(self)

            def finish(self):
                RoundupRequestHandler.finish(self)
                if self.CONFIG["SSL"]:
                    self.request.shutdown()
                    self.request.close()

        if self["SSL"]:
            base_server = SecureHTTPServer
        else:
            # time out after a minute if we can
            # This sets the socket to non-blocking. SSL needs a blocking
            # socket, so we do this only for non-SSL connections.
            if hasattr(socket, 'setdefaulttimeout'):
                socket.setdefaulttimeout(60)
            base_server = http_.server.HTTPServer

        # obtain request server class
        if self["MULTIPROCESS"] not in MULTIPROCESS_TYPES:
            print(_("Multiprocess mode \"%s\" is not available, "
                    "switching to single-process") % self["MULTIPROCESS"])
            self["MULTIPROCESS"] = "none"
            server_class = base_server
        elif self["MULTIPROCESS"] == "fork":
            class ForkingServer(socketserver.ForkingMixIn,
                                base_server):
                pass
            server_class = ForkingServer
            server_class.max_children = self["MAX_CHILDREN"]
        elif self["MULTIPROCESS"] == "thread":
            class ThreadingServer(socketserver.ThreadingMixIn,
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
        except socket.error as e:
            if e.args[0] == errno.EADDRINUSE:
                raise socket.error(_("Unable to bind to port %s, "
                                     "port already in use.") % self["PORT"])
            if e.args[0] == errno.EACCES:
                raise socket.error(_(
                    "Unable to bind to port %(port)s, "
                    "access not allowed, "
                    "errno: %(errno)s %(msg)s") % {
                        "port": self["PORT"],
                        "errno": e.args[0],
                        "msg": e.args[1]}
                )

            raise
        # change user and/or group
        setgid(self["GROUP"])
        setuid(self["USER"])
        # return the server
        return httpd


try:
    import win32serviceutil
except ImportError:
    RoundupService = None
else:

    # allow the win32
    import win32service

    class SvcShutdown(BaseException):
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
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_ERROR_TYPE,
                    servicemanager.PYS_SERVICE_STOPPED,
                    (self._svc_display_name_, "\r\nMissing logfile option"))
                self.ReportServiceStatus(win32service.SERVICE_STOPPED)
                return
            config.set_logging()
            self.server = config.get_server()
            self.running = 1
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                                  servicemanager.PYS_SERVICE_STARTED,
                                  (self._svc_display_name_,
                                   " at %s:%s" % (config["HOST"],
                                                  config["PORT"])))
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
               specified if -d is used.
 -D            run the server in the foreground even when -d is used.'''
    if message:
        message += '\n\n'
    print(_('''\n%(message)sUsage: roundup-server [options] [name=tracker home]*

Options:
 -v            print the Roundup version number and exit
 -h            print this text and exit
 -S            create or update configuration file and exit
 -C <fname>    use configuration file <fname>
 -n <name>     set the host name of the Roundup web server instance,
               specifies on which network interfaces to listen for
               connections, defaults to localhost, use 0.0.0.0 to bind
               to all network interfaces
 -p <port>     set the port to listen on (default: %(port)s)
 -I <header1[,header2]*> list of headers to pass to the backend
 -l <fname>    log to the file indicated by fname instead of stderr/stdout
 -N            log client machine names instead of IP addresses (much slower)
 -i <fname>    set tracker index template
 -m <children> maximum number of children to spawn in fork multiprocess mode
 -s            enable SSL
 -L            http request logging uses python logging (roundup.http)
 -P            log client address/name using reverse proxy X-Forwarded-For
               header and not the connection IP (which is the reverse proxy).
               Appends a '+' sign to the logged address/name.
 -e <fname>    PEM file containing SSL key and certificate
 -t <mode>     multiprocess mode (default: %(mp_def)s).
               Allowed values: %(mp_types)s.
 -V <version>  set HTTP version (default: HTTP/1.1).
               Allowed values: HTTP/1.0, HTTP/1.1.

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
})


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
    config = ServerConfig()
    # additional options
    short_options = "hvSc"
    try:
        (optlist, args) = config.getopt(sys.argv[1:],
                                        short_options,
                                        ("help", "version", "save-config",))
    except (getopt.GetoptError, configuration.ConfigurationError) as e:
        usage(str(e))
        return

    # if running in windows service mode, don't do any other stuff
    if ("-c", "") in optlist:
        global RoundupService
        if not RoundupService:
            RoundupService = True  # make sure usage displays -c help text
            error_m = """
ERROR: -c is not available because roundup couldn't import
   win32serviceutil from pywin32. See Installation docs
   for pywin32 details.
            """
            usage(error_m)
            return

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
                raise ValueError(_("Instances must be name=home"))
            config.add_option(TrackerHomeOption(config, "trackers", name))
            config["TRACKERS_" + name.upper()] = home

    # handle remaining options
    if optlist:
        for (opt, _arg) in optlist:
            if opt in ("-h", "--help"):
                usage()
            elif opt in ("-v", "--version"):
                print('%s (python %s)' % (roundup_version,
                                          sys.version.split()[0]))
            elif opt in ("-S", "--save-config"):
                config.save()
                print(_("Configuration saved to %s") % config.filepath)
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
        if not (config["LOGFILE"] or config["LOGHTTPVIALOGGER"]):
            print(_("If you specify a PID file you must use -l or -L."))
            sys.exit(1)

    # fork the server from our parent if a pidfile is specified
    if config["PIDFILE"]:
        if not hasattr(os, 'fork'):
            print(_("Sorry, you can't run the server as a daemon"
                    " on this Operating System"))
            sys.exit(0)
        else:
            if config['NODAEMON']:
                writepidfile(config["PIDFILE"])
            else:
                daemonize(config["PIDFILE"])

    # create the server
    try:
        httpd = config.get_server()
    except Exception as e:
        # capture all exceptions and pretty print them
        print(e)
        sys.exit(2)

    if success_message:
        print(success_message)
    else:
        print(_('Roundup server started on %(HOST)s:%(PORT)s')
              % config)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('Keyboard Interrupt: exiting')
        try:
            httpd.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            # forced shutdown can throw an error.
            # we don't care as we are going away.
            pass
        httpd.socket.close()


if __name__ == '__main__':
    run()

# vim: sts=4 sw=4 et si
