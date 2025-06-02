"""WWW request handler (also used in the stand-alone server).
"""
__docformat__ = 'restructuredtext'

import base64
import binascii
import codecs
import email.utils
import errno
import logging
import mimetypes
import os
import re
import socket
import stat
import sys
import time
from email.mime.multipart import MIMEMultipart
from traceback import format_exc

try:
    from OpenSSL.SSL import SysCallError
except ImportError:
    class SysCallError(Exception):
        pass

import roundup.anypy.email_  # noqa: F401  -- patches for email library code
from roundup import hyperdb, rest, xmlrpc

# quality of random checked below
from roundup.anypy import http_, random_, urllib_, xmlrpc_
from roundup.anypy.cgi_ import cgi
from roundup.anypy.cookie_ import BaseCookie, CookieError, SimpleCookie, get_cookie_date
from roundup.anypy.html import html_escape
from roundup.anypy.strings import b2s, bs2b, is_us, s2b, uchr
from roundup.cgi import TranslationService, accept_language, actions, cgitb, templating
from roundup.cgi.exceptions import (
    DetectorError,
    FormError,
    IndexerQueryError,
    NotFound,
    NotModified,
    Redirect,
    SendFile,
    SendStaticFile,
    SeriousError,
)
from roundup.cgi.form_parser import FormParser
from roundup.exceptions import (
    LoginError,
    RateLimitExceeded,
    Reject,
    RejectRaw,
    Unauthorised,
    UsageError,
)

from roundup.mlink_expr import ExpressionError

from roundup.mailer import Mailer, MessageSendError

logger = logging.getLogger('roundup')

if not random_.is_weak:
    logger.debug("Importing good random generator")
else:
    logger.warning("**SystemRandom not available. Using poor random generator")


def initialiseSecurity(security):
    '''Create some Permissions and Roles on the security object

    This function is directly invoked by security.Security.__init__()
    as a part of the Security object instantiation.
    '''
    p = security.addPermission(
        name="Web Access",
        description="User may access the web interface")
    security.addPermissionToRole('Admin', p)

    p = security.addPermission(
        name="Rest Access",
        description="User may access the rest interface")
    security.addPermissionToRole('Admin', p)

    p = security.addPermission(
        name="Xmlrpc Access",
        description="User may access the xmlrpc interface")
    security.addPermissionToRole('Admin', p)

    # doing Role stuff through the web - make sure Admin can
    # TODO: deprecate this and use a property-based control
    p = security.addPermission(
        name="Web Roles",
        description="User may manipulate user Roles through the web")
    security.addPermissionToRole('Admin', p)


def add_message(msg_list, msg, escape=True):
    if escape:
        msg = html_escape(msg, quote=False).replace('\n', '<br />\n')
    else:
        msg = msg.replace('\n', '<br />\n')
    msg_list.append(msg)
    return msg_list  # for unittests

# if set to False via interfaces.py do not log a warning when
# xmlrpc is used and defusedxml is not installed.
WARN_FOR_MISSING_DEFUSEDXML = True

default_err_msg = ''"""<html><head><title>An error has occurred</title></head>
<body><h1>An error has occurred</h1>
<p>A problem was encountered processing your request.
The tracker maintainers have been notified of the problem.</p>
</body></html>"""


def seed_pseudorandom():
    '''A function to seed the default pseudorandom random number generator
       which is used to (at minimum):
          * generate part of email message-id
          * generate OTK for password reset
          * generate the temp recovery password

       This function limits the scope of the 'import random' call
       as the random identifier is used throughout the code and
       can refer to SystemRandom.
    '''
    import random
    random.seed()


class LiberalCookie(SimpleCookie):
    """ Python's SimpleCookie throws an exception if the cookie uses invalid
        syntax.  Other applications on the same server may have done precisely
        this, preventing roundup from working through no fault of roundup.
        Numerous other python apps have run into the same problem:

        trac: http://trac.edgewall.org/ticket/2256
        mailman: http://bugs.python.org/issue472646

        This particular implementation comes from trac's solution to the
        problem. Unfortunately it requires some hackery in SimpleCookie's
        internals to provide a more liberal __set method.
    """
    def load(self, rawdata, ignore_parse_errors=True):
        if ignore_parse_errors:
            self.bad_cookies = []
            self._BaseCookie__set = self._loose_set
        SimpleCookie.load(self, rawdata)
        if ignore_parse_errors:
            self._BaseCookie__set = self._strict_set
            for key in self.bad_cookies:
                del self[key]

    _strict_set = BaseCookie._BaseCookie__set

    def _loose_set(self, key, real_value, coded_value):
        try:
            self._strict_set(key, real_value, coded_value)
        except CookieError:
            self.bad_cookies.append(key)
            dict.__setitem__(self, key, None)


class Session:
    """
    Needs DB to be already opened by client

    Session attributes at instantiation:

    - "client" - reference to client for add_cookie function
    - "session_db" - session DB manager
    - "cookie_name" - name of the cookie with session id
    - "_sid" - session id for current user
    - "_data" - session data cache

    session = Session(client)
    session.set(name=value)
    value = session.get(name)

    session.destroy()  # delete current session
    session.clean_up() # clean up session table

    session.update(set_cookie=True, expire=3600*24*365)
                       # refresh session expiration time, setting persistent
                       # cookie if needed to last for 'expire' seconds

    """

    def __init__(self, client):
        self._data = {}
        self._sid = None

        self.client = client
        self.session_db = client.db.getSessionManager()

        # parse cookies for session id
        if self.client.secure:
            cookie_template = '__Secure-roundup_session_%s'
        else:
            cookie_template = 'roundup_session_%s'
        self.cookie_name = cookie_template % \
                re.sub('[^a-zA-Z]', '', client.instance.config.TRACKER_NAME)
        cookies = LiberalCookie(client.env.get('HTTP_COOKIE', ''))
        if self.cookie_name in cookies:
            try:
                self._sid = cookies[self.cookie_name].value
                self._data = self.session_db.getall(self._sid)
            except KeyError:
                self._sid = None
                # remove old cookie
                self.client.add_cookie(self.cookie_name, None)

    def _gen_sid(self):
        """ generate a unique session key """
        while 1:
            s = b2s(binascii.b2a_base64(random_.token_bytes(32)).strip()).rstrip('=')
            if not self.session_db.exists(s):
                break

        return s

    def clean_up(self):
        """Remove expired sessions"""
        self.session_db.clean()

    def destroy(self):
        self.client.add_cookie(self.cookie_name, None)
        self._data = {}
        if self._sid:
            self.session_db.destroy(self._sid)
            self.session_db.commit()

    def get(self, name, default=None):
        return self._data.get(name, default)

    def set(self, **kwargs):
        self._data.update(kwargs)
        if not self._sid:
            self._sid = self._gen_sid()
            self.session_db.set(self._sid, **self._data)
            # add session cookie
            self.update(set_cookie=True)

            # XXX added when patching 1.4.4 for backward compatibility
            # XXX remove
            self.client.session = self._sid
        else:
            self.session_db.set(self._sid, **self._data)
            self.session_db.commit()

    def update(self, set_cookie=False, expire=None):
        """ update timestamp in db to avoid expiration

            if 'set_cookie' is True, set cookie with 'expire' seconds lifetime
            if 'expire' is None - session will be closed with the browser

            XXX the session can be purged within a week even if a cookie
                lifetime is longer
        """
        self.session_db.updateTimestamp(self._sid)
        self.session_db.commit()

        if set_cookie:
            self.client.add_cookie(self.cookie_name, self._sid, expire=expire)


# import from object as well so it's a new style object and I can use super()
class BinaryFieldStorage(cgi.FieldStorage, object):
    '''This class works around the bug https://bugs.python.org/issue27777.

       cgi.FieldStorage must save all data as binary/bytes. This is
       needed for handling json and xml data blobs under python
       3. Under python 2, str and binary are interchangable, not so
       under 3.
    '''
    def make_file(self, mode=None):
        ''' work around https://bugs.python.org/issue27777 '''
        import tempfile
        if self.length >= 0:
            return tempfile.TemporaryFile("wb+")
        return super(BinaryFieldStorage, self).make_file()


class Client:
    """Instantiate to handle one CGI request.

    See inner_main for request processing.

    Client attributes at instantiation:

    - "path" is the PATH_INFO inside the instance (with no leading '/')
    - "base" is the base URL for the instance
    - "form" is the cgi form, an instance of FieldStorage from the standard
      cgi module
    - "additional_headers" is a dictionary of additional HTTP headers that
      should be sent to the client
    - "response_code" is the HTTP response code to send to the client
    - "translator" is TranslationService instance
    - "client-nonce" is a unique value for this client connection. Can be
       used as a nonce for CSP headers and to sign javascript code
       presented to the browser. This is different from the CSRF nonces
       and can not be used for anti-csrf measures.

    During the processing of a request, the following attributes are used:

    - "db"
    - "_error_message" holds a list of error messages
    - "_ok_message" holds a list of OK messages
    - "session" is deprecated in favor of session_api (XXX remove)
    - "session_api" is the interface to store data in session
    - "user" is the current user's name
    - "userid" is the current user's id
    - "template" is the current :template context
    - "classname" is the current class context name
    - "nodeid" is the current context item id

    Note: _error_message and _ok_message should not be modified
    directly, use add_ok_message and add_error_message, these, by
    default, escape the message added to avoid XSS security issues.

    User Identification:
     Users that are absent in session data are anonymous and are logged
     in as that user. This typically gives them all Permissions assigned
     to the Anonymous Role.

     Every user is assigned a session. "session_api" is the interface
     to work with session data.

    Special form variables:
     Note that in various places throughout this code, special form
     variables of the form :<name> are used. The colon (":") part may
     actually be one of either ":" or "@".
    """

    # charset used for data storage and form templates
    # Note: must be in lower case for comparisons!
    # XXX take this from instance.config?
    STORAGE_CHARSET = 'utf-8'

    #
    # special form variables
    #
    FV_TEMPLATE = re.compile(r'[@:]template')
    FV_OK_MESSAGE = re.compile(r'[@:]ok_message')
    FV_ERROR_MESSAGE = re.compile(r'[@:]error_message')

    # Note: index page stuff doesn't appear here:
    # columns, sort, sortdir, filter, group, groupdir, search_text,
    # pagesize, startwith

    # list of network error codes that shouldn't be reported to tracker admin
    # (error descriptions from FreeBSD intro(2))
    IGNORE_NET_ERRORS = (
        # A write on a pipe, socket or FIFO for which there is
        # no process to read the data.
        errno.EPIPE,
        # A connection was forcibly closed by a peer.
        # This normally results from a loss of the connection
        # on the remote socket due to a timeout or a reboot.
        errno.ECONNRESET,
        # Software caused connection abort.  A connection abort
        # was caused internal to your host machine.
        errno.ECONNABORTED,
        # A connect or send request failed because the connected party
        # did not properly respond after a period of time.
        errno.ETIMEDOUT,
    )

    # Cache_Control[key] = Cache-Control header value
    # Key can be explicitly file basename - value applied to just that file
    #     takes precedence over mime type.
    # Key can be mime type - all files of that mimetype will get the value
    Cache_Control = {
        'application/javascript': "public, max-age=1209600",  # 2 weeks
        'text/javascript': "public, max-age=1209600",         # 2 weeks
        'text/css':               "public, max-age=4838400",  # 8 weeks/2 mnths
    }

    # list of valid http compression (Content-Encoding) algorithms
    # we have available
    compressors = []
    try:
        # Only one provided by standard library
        import gzip
        compressors.append('gzip')
    except ImportError:
        pass
    try:
        import brotli
        compressors.append('br')
    except ImportError:
        pass
    try:
        import zstd
        compressors.append('zstd')
    except ImportError:
        pass

    # everything not here is served as 'application/octet-stream'
    # Moved to class so it can be modified from interfaces.py
    # Adding:
    #  from roundup.cgi.client import Client
    #  Client.mime_type_allowlist.append('application/pdf')
    # will permit pdf files to be displayed in the browser rather than
    # downloaded to a file.

    mime_type_allowlist = [
        'text/plain',
        'text/x-csrc',    # .c
        'text/x-chdr',    # .h
        'text/x-patch',   # .patch and .diff
        'text/x-python',  # .py
        'text/xml',
        'text/csv',
        'text/css',
        'image/gif',
        'image/jpeg',
        'image/png',
        'image/svg+xml',
        'image/webp',
        'audio/ogg',
        'video/webm',
    ]

    # mime types of files that are already compressed and should not be
    # compressed on the fly. Can be extended/reduced using interfaces.py.
    # This excludes types from being compressed. Should we have a list
    # of mime types we should compress? write_html() calls compress_encode
    # which uses this without a content-type so that's an issue.
    # Also for text based data, might have charset too so need to parse
    # content-type.
    precompressed_mime_types = ["image/png", "image/jpeg"]

    def __init__(self, instance, request, env, form=None, translator=None):
        # re-seed the random number generator. Is this is an instance of
        # random.SystemRandom it has no effect.
        random_.seed()
        # So we also seed the pseudorandom random source obtained from
        #    import random
        # to make sure that every forked copy of the client will return
        # new random numbers.
        seed_pseudorandom()
        self.start = time.time()
        self.instance = instance
        self.request = request
        self.env = env
        if translator is not None:
            self.setTranslator(translator)
            # XXX we should set self.language to "translator"'s language,
            # but how to get it ?
            self.language = ""
        else:
            self.setTranslator(TranslationService.NullTranslationService())
            self.language = ""  # as is the default from determine_language

        self.mailer = Mailer(instance.config)
        # If True the form contents wins over the database contents when
        # rendering html properties. This is set when an error occurs so
        # that we don't lose submitted form contents.
        self.form_wins = False

        # save off the path
        self.path = env['PATH_INFO']

        # this is the base URL for this tracker
        self.base = self.instance.config.TRACKER_WEB

        # should cookies be secure?
        self.secure = self.base.startswith('https')

        # check the tracker_web setting
        if not self.base.endswith('/'):
            self.base = self.base + '/'

        # this is the "cookie path" for this tracker (ie. the path part of
        # the "base" url)
        self.cookie_path = urllib_.urlparse(self.base)[2]
        # cookies to set in http responce
        # {(path, name): (value, expire)}
        self._cookies = {}

        # define a unique nonce. Can be used for Content Security Policy
        # nonces for scripts.
        self.client_nonce = self._gen_nonce()

        # see if we need to re-parse the environment for the form (eg Zope)
        if form is None:
            # cgi.FieldStorage doesn't special case OPTIONS, DELETE or
            # PATCH verbs. They are processed like POST. So FieldStorage
            # hangs on these verbs trying to read posted data that
            # will never arrive.
            # If not defined, set CONTENT_LENGTH to 0 so it doesn't
            # hang reading the data.
            if self.env['REQUEST_METHOD'] in ['OPTIONS', 'DELETE', 'PATCH'] \
                and 'CONTENT_LENGTH' not in self.env:
                self.env['CONTENT_LENGTH'] = 0
                logger.debug("Setting CONTENT_LENGTH to 0 for method: %s",
                             self.env['REQUEST_METHOD'])

            # cgi.FieldStorage must save all data as
            # binary/bytes. Subclass BinaryFieldStorage does this.
            # It's a workaround for a bug in cgi.FieldStorage. See class
            # def for details.
            self.form = BinaryFieldStorage(fp=request.rfile, environ=env)
        else:
            self.form = form

        # When the CONTENT-TYPE is not 'application/x-www-form-urlencoded':
        # or multipart/*, cgi.(Mini)FieldStorage sets the list property to
        # None. Initialize an empty list property in this case so we can
        # query the list in all cases.
        try:
            if (self.form.list is None):
                self.form.list = []
        except AttributeError:
            # self.form should always be some type of
            # FieldStorage. If we get an AttributeError,
            # print what the form is.
            # FIXME: plan on removing this in 2028 to improve
            # performance if there are no reports of it being triggered.
            logger.error(("Invalid self.form found (please report "
                         "to the roundup-users mailing list): %s") % self.form)
            raise

        # turn debugging on/off
        try:
            self.debug = int(env.get("ROUNDUP_DEBUG", 0))
        except ValueError:
            # someone gave us a non-int debug level, turn it off
            self.debug = 0

        # flag to indicate that the HTTP headers have been sent
        self.headers_done = 0

        # record of headers sent for debugging
        self.headers_sent = []

        # additional headers to send with the request - must be registered
        # before the first write
        self.additional_headers = {}
        self.response_code = 200

        # default character set
        self.charset = self.STORAGE_CHARSET

        # parse cookies (used for charset lookups)
        # use our own LiberalCookie to handle bad apps on the same
        # server that have set cookies that are out of spec
        self.cookie = LiberalCookie(self.env.get('HTTP_COOKIE', ''))

        self.user = None
        self.userid = None
        self.nodeid = None
        self.classname = None
        self.template = None
        self._ok_message = []
        self._error_message = []

    def _gen_nonce(self):
        """ generate a unique nonce """
        return b2s(base64.b32encode(random_.token_bytes(40)))

    def setTranslator(self, translator=None):
        """Replace the translation engine

        'translator'
           is TranslationService instance.
           It must define methods 'translate' (TAL-compatible i18n),
           'gettext' and 'ngettext' (gettext-compatible i18n).

           If omitted, create default TranslationService.
        """
        if translator is None:
            translator = TranslationService.get_translation(
                language=self.instance.config["TRACKER_LANGUAGE"],
                tracker_home=self.instance.config["TRACKER_HOME"])
        self.translator = translator
        self._ = self.gettext = translator.gettext
        self.ngettext = translator.ngettext

    def main(self):
        """ Wrap the real main in a try/finally so we always close off the db.
        """

        # strip HTTP_PROXY issue2550925 in case
        # PROXY header is set.
        if 'HTTP_PROXY' in self.env:
            del (self.env['HTTP_PROXY'])
        if 'HTTP_PROXY' in os.environ:
            del (os.environ['HTTP_PROXY'])

        xmlrpc_enabled = self.instance.config.WEB_ENABLE_XMLRPC
        rest_enabled = self.instance.config.WEB_ENABLE_REST
        try:
            if xmlrpc_enabled and self.path == 'xmlrpc':
                self.handle_xmlrpc()
            elif rest_enabled and (self.path == 'rest' or
                                   self.path[:5] == 'rest/'):
                self.handle_rest()
            else:
                self.inner_main()
        finally:
            if hasattr(self, 'db'):
                self.db.close()

    def handle_xmlrpc(self):
        if self.env.get('CONTENT_TYPE') != 'text/xml':
            self.write(
                b"This is the endpoint of Roundup <a href='" +
                b"https://www.roundup-tracker.org/docs/xmlrpc.html'>" +
                b"XML-RPC interface</a>.")
            return

        # Pull the raw XML out of the form.  The "value" attribute
        # will be the raw content of the POST request.
        assert self.form.file
        input_data = self.form.value
        # So that the rest of Roundup can query the form in the
        # usual way, we create an empty list of fields.
        self.form.list = []

        # Set the charset and language, since other parts of
        # Roundup may depend upon that.
        self.determine_charset()
        if self.instance.config["WEB_TRANSLATE_XMLRPC"]:
            self.determine_language()
        # Open the database as the correct user.
        try:
            self.determine_user(is_api="xmlrpc")
            self.db.tx_Source = "xmlrpc"
            self.db.i18n = self.translator
        except LoginError as msg:
            output = xmlrpc_.client.dumps(
                xmlrpc_.client.Fault(401, "%s" % msg),
                allow_none=True)
            self.setHeader("Content-Type", "text/xml")
            self.setHeader("Content-Length", str(len(output)))
            self.write(s2b(output))
            return
        except RateLimitExceeded as msg:
            output = xmlrpc_.client.dumps(
                xmlrpc_.client.Fault(429, "%s" % msg),
                allow_none=True)
            self.setHeader("Content-Type", "text/xml")
            self.setHeader("Content-Length", str(len(output)))
            self.write(s2b(output))
            return

        if not self.db.security.hasPermission('Xmlrpc Access', self.userid):
            output = xmlrpc_.client.dumps(
                xmlrpc_.client.Fault(403, "Forbidden"),
                allow_none=True)
            self.setHeader("Content-Type", "text/xml")
            self.setHeader("Content-Length", str(len(output)))
            self.write(s2b(output))
            return

        self.check_anonymous_access()

        try:
            # coverting from function returning true/false to
            # raising exceptions
            # Call csrf with xmlrpc checks enabled.
            # It will return True if everything is ok,
            # raises exception on check failure.
            csrf_ok = self.handle_csrf(api=True)
        except (Unauthorised, UsageError):
            # report exception back to server
            exc_type, exc_value, exc_tb = sys.exc_info()
            output = xmlrpc_.client.dumps(
                xmlrpc_.client.Fault(1, "%s:%s" % (exc_type, exc_value)),
                allow_none=True)
            csrf_ok = False  # we had an error, failed check

        if csrf_ok is True:
            if WARN_FOR_MISSING_DEFUSEDXML and (not xmlrpc_.client.defusedxml):
                logger.warning(self._("XMLRPC endpoint is not using defusedxml. Improve security by installing defusedxml."))
            handler = xmlrpc.RoundupDispatcher(self.db,
                                               self.instance.actions,
                                               self.translator,
                                               allow_none=True)
            output = handler.dispatch(input_data)

        self.setHeader("Content-Type", "text/xml")
        self.setHeader("Content-Length", str(len(output)))
        self.write(output)

    def is_cors_preflight(self):
        return (
            self.env['REQUEST_METHOD'] == "OPTIONS"
            and self.request.headers.get("Access-Control-Request-Method")
               # technically Access-Control-Request-Headers (ACRH) is
               # optional, but we require the header x-requested-with,
               # so ACRH will be present.
            and self.request.headers.get("Access-Control-Request-Headers")
            and self.request.headers.get("Origin"))

    def handle_preflight(self):
        # Call rest library to handle the pre-flight request
        handler = rest.RestfulInstance(self, self.db)
        output = handler.dispatch(self.env['REQUEST_METHOD'],
                                  self.path, self.form)

        if self.response_code == 204:
            self.write("")
        else:
            self.setHeader("Content-Length", str(len(output)))
            self.write(output)

    def reject_request(self, message, message_type="text/plain",
                       status=http_.client.UNAUTHORIZED):
        self.response_code = status
        self.setHeader("Content-Length", str(len(message)))
        self.setHeader("Content-Type", message_type)
        self.write(message)

    def handle_rest(self):
        # Set the charset and language
        self.determine_charset()
        if self.instance.config["WEB_TRANSLATE_REST"]:
            self.determine_language()
        # Open the database as the correct user.
        # TODO: add everything to RestfulDispatcher
        try:
            self.determine_user(is_api="rest")
            self.db.tx_Source = "rest"
            self.db.i18n = self.translator
        except LoginError as err:
            output = s2b("Invalid Login - %s" % str(err))
            self.reject_request(output, status=http_.client.UNAUTHORIZED)
            return
        except RateLimitExceeded as err:
            output = s2b("%s" % str(err))
            self.reject_request(output,
                                status=http_.client.TOO_MANY_REQUESTS)
            return

        # Handle CORS preflight request. We know rest is enabled
        # because handle_rest is called. Preflight requests
        # are unauthenticated, so no need to check permissions.
        if (self.is_cors_preflight()):
                # Origin header must be defined to get here
            if self.is_origin_header_ok(api=True):
                self.handle_preflight()
            else:
                # origin is not authorized for REST
                msg = self._("Client is not allowed to use Rest Interface.")
                output = s2b(
                    '{ "error": { "status": 400, "msg": "%s" } }' % msg)
                self.reject_request(output,
                                message_type="application/json",
                                status=400)
            return

        if not self.db.security.hasPermission('Rest Access', self.userid):
            output = s2b('{ "error": { "status": 403, "msg": "Forbidden." } }')
            self.reject_request(output,
                                message_type="application/json",
                                status=403)
            return

        # verify Origin is allowed on all requests including GET.
        # If a GET, missing origin is allowed  (i.e. same site GET request)
        if not self.is_origin_header_ok(api=True):
            if 'HTTP_ORIGIN' not in self.env:
                msg = self._("Required Header Missing")
                err = "REST request missing 'Origin' header by user %(user)s."
            else:
                msg = self._("Client is not allowed to use Rest Interface.")
                err = "REST request 'Origin' (%(origin)s) unauthorized by user %(user)s."

            # Use code 400. Codes 401 and 403 imply that authentication
            # is needed or authenticated person is not authorized.
            output = s2b(
                '{ "error": { "status": 400, "msg": "%s" } }' % msg)
            self.reject_request(output,
                                message_type="application/json",
                                status=400)
            # Would be nice to log the original source address here to
            # allow firewalling in case of abuse/attack. Especially if
            # anonymous is allowed REST access. However,
            #    self.request.connection.getpeername()
            # only gets us 127.0.0.1 when a proxy is used. I think the
            # same is true of wsgi mode (but it might be a UNIX domain
            # socket address). The upstream server needs to supply the
            # real IP as it sees it and we need to consume it. There
            # is no method for this that handles all the ways roundup
            # can be run AFAIK. So no IP address, just user.
            logger.error(err, {"user": self.user,
                               "origin": self.env.get('HTTP_ORIGIN', None)})
            return

        self.check_anonymous_access()

        try:
            # Call csrf with api (xmlrpc, rest) checks enabled.
            # It will return True if everything is ok,
            # raises exception on check failure.
            # Note this returns true for a GET request.
            # Must check supplied Origin header for bad value first.
            csrf_ok = self.handle_csrf(api=True)
        except (Unauthorised, UsageError) as msg:
            # FIXME should format return value according to
            # client's accept header, so application/xml, text/plain etc..
            output = s2b('{ "error": { "status": 400, "msg": "%s"}}' %
                         str(msg))
            self.reject_request(output,
                                message_type="application/json",
                                status=400)
            csrf_ok = False  # we had an error, failed check
            return

        # With the return above the if will never be false,
        # Keeping the if so we can remove return to pass
        # output though and format output according to accept
        # header.
        if csrf_ok is True:
            # Call rest library to handle the request
            handler = rest.RestfulInstance(self, self.db)
            output = handler.dispatch(self.env['REQUEST_METHOD'],
                                      self.path, self.form)

        # type header set by rest handler
        # self.setHeader("Content-Type", "text/xml")
        if self.response_code == 204:  # no body with 204
            self.write("")
        else:
            self.setHeader("Content-Length", str(len(output)))
            self.write(output)

    def add_ok_message(self, msg, escape=True):
        add_message(self._ok_message, msg, escape)

    def add_error_message(self, msg, escape=True):
        add_message(self._error_message, msg, escape)
        # Want to interpret form values when rendering when an error
        # occurred:
        self.form_wins = True

    def inner_main(self):
        """Process a request.

        The most common requests are handled like so:

        1. look for charset and language preferences, set up user locale
           see determine_charset, determine_language
        2. figure out who we are, defaulting to the "anonymous" user
           see determine_user
        3. figure out what the request is for - the context
           see determine_context
        4. handle any requested action (item edit, search, ...)
           see handle_action
        5. render a template, resulting in HTML output

        In some situations, exceptions occur:

        - HTTP Redirect  (generally raised by an action)
        - SendFile       (generally raised by determine_context)
          serve up a FileClass "content" property
        - SendStaticFile (generally raised by determine_context)
          serve up a file from the tracker "html" directory
        - Unauthorised   (generally raised by an action)
          the action is cancelled, the request is rendered and an error
          message is displayed indicating that permission was not
          granted for the action to take place
        - templating.Unauthorised   (templating action not permitted)
          raised by an attempted rendering of a template when the user
          doesn't have permission
        - NotFound       (raised wherever it needs to be)
          percolates up to the CGI interface that called the client
        """
        self._ok_message = []
        self._error_message = []
        try:
            self.determine_charset()

            try:
                # make sure we're identified (even anonymously)
                self.determine_user()

                # figure out the context and desired content template
                self.determine_context()

                self.determine_language()
                self.db.i18n = self.translator

                # if we've made it this far the context is to a bit of
                # Roundup's real web interface (not a file being served up)
                # so do the Anonymous Web Access check now
                self.check_anonymous_access()

                # check for a valid csrf token identifying the right user
                csrf_ok = True
                try:
                    # coverting from function returning true/false to
                    # raising exceptions
                    csrf_ok = self.handle_csrf()
                except (UsageError, Unauthorised) as msg:
                    csrf_ok = False
                    self.form_wins = True
                    self.add_error_message(' '.join(msg.args))

                # If csrf checks pass. Run actions etc.
                # handle_action() may handle a form submit action.
                # It can change self.classname and self.template,
                # and may also append error/ok_messages.
                html = self.handle_action() if csrf_ok else None

                if html:
                    self.write_html(html)
                    return

                # now render the page
                # we don't want clients caching our dynamic pages
                self.additional_headers['Cache-Control'] = 'no-cache'

                # pages with messages added expire right now
                # simple views may be cached for a small amount of time
                # TODO? make page expire time configurable
                # <rj> always expire pages, as IE just doesn't seem to do the
                # right thing here :(
                date = time.time() - 1
                # if self._error_message or self._ok_message:
                #    date = time.time() - 1
                # else:
                #    date = time.time() + 5
                self.additional_headers['Expires'] = \
                    email.utils.formatdate(date, usegmt=True)

                # render the content
                self.write_html(self.renderContext())
            except SendFile as designator:
                # The call to serve_file may result in an Unauthorised
                # exception or a NotModified exception.  Those
                # exceptions will be handled by the outermost set of
                # exception handlers.
                self.determine_language()
                self.db.i18n = self.translator
                # prevent application/octet-stream mime type in header
                # from being changed to some other type by the browser
                # when mime sniffing.
                self.setHeader("X-Content-Type-Options", "nosniff")
                # prevent script execution in downloaded SVG, XML files
                # (or HTML files if enabled).
                self.setHeader("Content-Security-Policy", "script-src 'none'")
                self.serve_file(designator)
            except SendStaticFile as file:
                self.serve_static_file(str(file))
            except IOError:
                # IOErrors here are due to the client disconnecting before
                # receiving the reply.
                pass
            except SysCallError:
                # OpenSSL.SSL.SysCallError is similar to IOError above
                pass
            except RateLimitExceeded:
                raise

        except SeriousError as message:
            self.write_html(str(message))
        except Redirect as url:
            # let's redirect - if the url isn't None, then we need to do
            # the headers, otherwise the headers have been set before the
            # exception was raised
            if url:
                self.additional_headers['Location'] = str(url)
                self.response_code = 302
            self.write_html('Redirecting to <a href="%s">%s</a>' % (url, url))
        except LoginError as message:
            # The user tried to log in, but did not provide a valid
            # username and password.  If we support HTTP
            # authorization, send back a response that will cause the
            # browser to prompt the user again.
            if self.instance.config.WEB_HTTP_AUTH:
                self.response_code = http_.client.UNAUTHORIZED
                realm = self.instance.config.TRACKER_NAME
                self.setHeader("WWW-Authenticate",
                               'Basic realm="%s"' % realm)
            else:
                self.response_code = http_.client.FORBIDDEN
            self.renderFrontPage(str(message))
        except Unauthorised as message:
            # users may always see the front page
            self.response_code = 403
            self.renderFrontPage(str(message))
        except NotModified:
            # send the 304 response
            self.response_code = 304
            self.header()
        except NotFound as e:
            if self.response_code == 400:
                # We can't find a parameter (e.g. property name
                # incorrect). Tell the user what was raised.
                # Do not change to the 404 template since the
                # base url is valid just query args are not.
                # copy the page format from SeriousError _str_ exception.
                error_page = """
                <html><head><title>Roundup issue tracker: An error has occurred</title>
                <link rel="stylesheet" type="text/css" href="@@file/style.css">
                </head>
                <body class="body" marginwidth="0" marginheight="0">
                   <p class="error-message">%s</p>
                </body></html>
                """
                self.write_html(error_page % str(e))
            else:
                self.response_code = 404
                self.template = '404'
                try:
                    # generates keyerror if class does not exist
                    self.db.getclass(self.classname)
                    self.write_html(self.renderContext())
                except KeyError:
                    # we can't map the URL to a class we know about
                    # reraise the NotFound and let roundup_server
                    # handle it
                    raise NotFound(e)
        except FormError as e:
            self.add_error_message(self._('Form Error: ') + str(e))
            self.write_html(self.renderContext())
        except RateLimitExceeded as e:
            self.add_error_message(str(e))
            self.write_html(self.renderContext())
        except IOError:
            # IOErrors here are due to the client disconnecting before
            # receiving the reply.
            # may happen during write_html and serve_file, too.
            pass
        except SysCallError:
            # OpenSSL.SSL.SysCallError is similar to IOError above
            # may happen during write_html and serve_file, too.
            pass
        except DetectorError as e:
            if not self.instance.config.WEB_DEBUG:
                # run when we are not in debug mode, so errors
                # go to admin too.
                self.send_error_to_admin(e.subject, e.html, e.txt)
                self.write_html(e.html)
            else:
                # in debug mode, only write error to screen.
                self.write_html(e.html)
        except Exception as e:  # noqa: F841
            # Something has gone badly wrong.  Therefore, we should
            # make sure that the response code indicates failure.
            if self.response_code == http_.client.OK:
                self.response_code = http_.client.INTERNAL_SERVER_ERROR
            # Help the administrator work out what went wrong.
            html = ("<h1>Traceback</h1>"
                    + cgitb.html(i18n=self.translator)
                    + ("<h1>Environment Variables</h1><table>%s</table>"
                       % cgitb.niceDict("", self.env)))
            if not self.instance.config.WEB_DEBUG:
                exc_info = sys.exc_info()
                subject = "Error: %s" % exc_info[1]
                self.send_error_to_admin(subject, html, format_exc())
                self.write_html(self._(default_err_msg))
            else:
                self.write_html(html)

    def clean_sessions(self):
        """Deprecated
           XXX remove
        """
        self.clean_up()

    def clean_up(self):
        """Remove expired sessions and One Time Keys.

           Do it only once an hour.
        """
        hour = 60 * 60
        now = time.time()

        # XXX: hack - use OTK table to store last_clean time information
        #      'last_clean' string is used instead of otk key
        otks = self.db.getOTKManager()
        last_clean = otks.get('last_clean', 'last_use', 0)
        if now - last_clean < hour:
            return

        self.session_api.clean_up()
        otks.clean()
        otks.set('last_clean', last_use=now)
        otks.commit()

    def determine_charset(self):
        """Look for client charset in the form parameters or browser cookie.

        If no charset requested by client, use storage charset (utf-8).

        If the charset is found, and differs from the storage charset,
        recode all form fields of type 'text/plain'
        """
        # look for client charset
        charset_parameter = 0
        # Python 2.6 form may raise a TypeError if list in form is None
        charset = None
        try:
            charset = self.form['@charset'].value
            if charset.lower() == "none":
                charset = ""
            charset_parameter = 1
        except (KeyError, TypeError):
            pass
        if charset is None and 'roundup_charset' in self.cookie:
            charset = self.cookie['roundup_charset'].value
        if charset:
            # make sure the charset is recognized
            try:
                codecs.lookup(charset)
            except LookupError:
                self.add_error_message(self._('Unrecognized charset: %r') %
                                       charset)

                charset_parameter = 0
            else:
                self.charset = charset.lower()
        # If we've got a character set in request parameters,
        # set the browser cookie to keep the preference.
        # This is done after codecs.lookup to make sure
        # that we aren't keeping a wrong value.
        if charset_parameter:
            self.add_cookie('roundup_charset', charset)

        # if client charset is different from the storage charset,
        # recode form fields
        # XXX this requires FieldStorage from Python library.
        #   mod_python FieldStorage is not supported!
        if self.charset != self.STORAGE_CHARSET:
            decoder = codecs.getdecoder(self.charset)
            encoder = codecs.getencoder(self.STORAGE_CHARSET)
            re_charref = re.compile('&#([0-9]+|x[0-9a-f]+);', re.IGNORECASE)

            def _decode_charref(matchobj):
                num = matchobj.group(1)
                uc = int(num[1:], 16) if num[0].lower() == 'x' else int(num)
                return uchr(uc)

            for field_name in self.form:
                field = self.form[field_name]
                if (field.type == 'text/plain') and not field.filename:
                    try:
                        value = decoder(field.value)[0]
                    except UnicodeError:
                        continue
                    value = re_charref.sub(_decode_charref, value)
                    field.value = encoder(value)[0]

    def determine_language(self):
        """Determine the language"""
        # look for language parameter
        # then for language cookie
        # last for the Accept-Language header
        # Python 2.6 form may raise a TypeError if list in form is None
        language = None
        try:
            language = self.form["@language"].value
            if language.lower() == "none":
                language = ""
            self.add_cookie("roundup_language", language)
        except (KeyError, TypeError):
            pass
        if language is None:
            if "roundup_language" in self.cookie:
                language = self.cookie["roundup_language"].value
            elif self.instance.config["WEB_USE_BROWSER_LANGUAGE"]:
                hal = self.env.get('HTTP_ACCEPT_LANGUAGE')
                language = accept_language.parse(hal)
            else:
                language = ""

        if not language:
            # default to tracker language
            language = self.instance.config["TRACKER_LANGUAGE"]

        # this maybe is not correct, as get_translation could not
        # find desired locale and switch back to "en" but we set
        # self.language to the desired language !
        self.language = language

        self.setTranslator(TranslationService.get_translation(
                language,
                tracker_home=self.instance.config["TRACKER_HOME"]))

    def authenticate_bearer_token(self, challenge):
        ''' authenticate the bearer token. Refactored from determine_user()
            to allow it to be overridden if needed.
        '''
        try:  # will jwt import?
            import jwt
        except ImportError:
            # no support for jwt, this is fine.
            self.setHeader("WWW-Authenticate", "Basic")
            raise LoginError('Support for jwt disabled.')

        # If first ',' separated token is < 32, jwt is disabled.
        # If second or later tokens are < 32 chars, the config system
        # stops the tracker from starting so insecure tokens can not
        # be used.
        CHARS_FOR_256_BIT_KEY = 32
        if len(self.db.config.WEB_JWT_SECRET[0]) < CHARS_FOR_256_BIT_KEY:
            # no support for jwt, this is fine.
            self.setHeader("WWW-Authenticate", "Basic")
            raise LoginError('Support for jwt disabled by admin.')

        last_error = "Unknown error validating bearer token."

        for secret in self.db.config.WEB_JWT_SECRET:
            try:  # handle jwt exceptions
                return jwt.decode(challenge, secret,
                                  algorithms=['HS256'],
                                  audience=self.db.config.TRACKER_WEB,
                                  issuer=self.db.config.TRACKER_WEB)

            except jwt.exceptions.InvalidSignatureError as err:
                # Try more signatures.
                # If all signatures generate InvalidSignatureError,
                # we exhaust the loop and last_error is used to
                # report the final (but not only) InvalidSignatureError
                last_error = str(err)  # preserve for end of loop
            except jwt.exceptions.InvalidTokenError as err:
                self.setHeader("WWW-Authenticate", "Basic, Bearer")
                self.make_user_anonymous()
                raise LoginError(str(err))

        # reach here only if no valid signature was found
        self.setHeader("WWW-Authenticate", "Basic, Bearer")
        self.make_user_anonymous()
        raise LoginError(last_error)

    def determine_user(self, is_api=False):
        """Determine who the user is"""
        self.opendb('admin')

        # if we get a jwt, it includes the roles to be used for this session
        # so we define a new function to encpsulate and return the jwt roles
        # and not take the roles from the database.
        override_get_roles = None

        # get session data from db
        # XXX: rename
        self.session_api = Session(self)

        # take the opportunity to cleanup expired sessions and otks
        self.clean_up()

        user = None
        # first up, try http authorization if enabled
        cfg = self.instance.config
        remote_user_header = cfg.WEB_HTTP_AUTH_HEADER or 'REMOTE_USER'
        if cfg.WEB_COOKIE_TAKES_PRECEDENCE:
            user = self.session_api.get('user')
            if user:
                # update session lifetime datestamp
                self.session_api.update()
                if remote_user_header in self.env:
                    del self.env[remote_user_header]
        if not user and cfg.WEB_HTTP_AUTH:
            if remote_user_header in self.env:
                # we have external auth (e.g. by Apache)
                user = self.env[remote_user_header]
                if cfg.WEB_HTTP_AUTH_CONVERT_REALM_TO_LOWERCASE and '@' in user:
                    u, d = user.split('@', 1)
                    user = '@'.join((u, d.lower()))
            elif self.env.get('HTTP_AUTHORIZATION', ''):
                # try handling Basic Auth ourselves
                auth = self.env['HTTP_AUTHORIZATION']
                try:
                    scheme, challenge = auth.split(' ', 1)
                except ValueError:
                    # Invalid header.
                    scheme = ''
                    challenge = ''
                if scheme.lower() == 'basic':
                    try:
                        decoded = b2s(base64.b64decode(challenge))
                    except TypeError:
                        # invalid challenge
                        decoded = ''
                    try:
                        username, password = decoded.split(':', 1)
                    except ValueError:
                        # Invalid challenge.
                        username = ''
                        password = ''
                    try:
                        # Current user may not be None, otherwise
                        # instatiation of the login action will fail.
                        # So we set the user to anonymous first.
                        self.make_user_anonymous()
                        login = self.get_action_class('login')(self)
                        login.verifyLogin(username, password, is_api=is_api)
                    except (LoginError, RateLimitExceeded):
                        self.make_user_anonymous()
                        raise
                    user = username
                    # try to seed with something harder to guess than
                    # just the time. If random is SystemRandom,
                    # this is a no-op.
                    random_.seed("%s%s" % (password, time.time()))
                elif scheme.lower() == 'bearer':
                    token = self.authenticate_bearer_token(challenge)

                    from roundup.hyperdb import iter_roles

                    # if we got here token is valid, use the role
                    # and sub claims.
                    try:
                        # make sure to str(token['sub']) the
                        # subject. As decoded by json, it is unicode
                        # which throws an error when used with 'nodeid
                        # in db' down the call chain.
                        user = self.db.user.get(str(token['sub']), 'username')
                    except IndexError:
                        raise LoginError("Token subject is invalid.")

                    # validate roles
                    all_rolenames = [role[0] for role in self.db.security.role.items()]
                    for r in token['roles']:
                        if r.lower() not in all_rolenames:
                            raise LoginError("Token roles are invalid.")

                    # will be used later to override the get_roles method
                    # having it defined as truthy allows it to be used.
                    override_get_roles = lambda self: iter_roles(  # noqa: ARG005
                        ','.join(token['roles']))

        # if user was not set by http authorization, try session lookup
        if not user:
            user = self.session_api.get('user')
            if user:
                # update session lifetime datestamp
                self.session_api.update()

        # if no user name set by http authorization or session lookup
        # the user is anonymous
        if not user:
            user = 'anonymous'

        # sanity check on the user still being valid,
        # getting the userid at the same time
        try:
            self.userid = self.db.user.lookup(user)
        except (KeyError, TypeError):
            user = 'anonymous'

        # make sure the anonymous user is valid if we're using it
        if user == 'anonymous':
            self.make_user_anonymous()
        else:
            self.user = user

        # reopen the database as the correct user
        self.opendb(self.user)
        if override_get_roles:
            # opendb destroys and re-opens the db if instance.optimize
            # is not true. This deletes an override of get_roles.  So
            # assign get_roles override from the jwt if needed at this
            # point.
            self.db.user.get_roles = override_get_roles

    def check_anonymous_access(self):
        """Check that the Anonymous user is actually allowed to use the web
        interface and short-circuit all further processing if they're not.
        """
        # allow Anonymous to use the "login" and "register" actions (noting
        # that "register" has its own "Register" permission check)

        action = ''
        try:
            if ':action' in self.form:
                action = self.form[':action']
            elif '@action' in self.form:
                action = self.form['@action']
        except TypeError:
            pass
        if isinstance(action, list):
            raise SeriousError(
                self._('broken form: multiple @action values submitted'))
        if action != '':
            # '' is value when no action parameter was found so run
            # this to extract action string value when action found.
            action = action.value.lower()
        if action in ('login', 'register'):
            return

        # allow Anonymous to view the "user" "register" template if they're
        # allowed to register
        if (self.db.security.hasPermission('Register', self.userid, 'user')
                and self.classname == 'user' and self.template == 'register'):
            return

        # otherwise for everything else
        if self.user == 'anonymous' and \
            not self.db.security.hasPermission('Web Access', self.userid):
                raise Unauthorised(self._("Anonymous users are not "
                                          "allowed to use the web interface"))

    def is_origin_header_ok(self, api=False, credentials=False):
        """Determine if origin is valid for the context

           Header is ok (return True) if ORIGIN is missing and it is a GET.
           Header is ok if ORIGIN matches the base url.
           If this is a API call:
             Header is ok if ORIGIN matches an element of allowed_api_origins.
             Header is ok if allowed_api_origins includes '*' as first
               element and credentials is False.
           Otherwise header is not ok.

           In a credentials context, if we match * we will return
           header is not ok. All credentialed requests must be
           explicitly matched.
        """

        try:
            origin = self.env['HTTP_ORIGIN']
        except KeyError:
            return self.env['REQUEST_METHOD'] == 'GET'

        # note base https://host/... ends host with with a /,
        # so add it to origin.
        foundat = self.base.find(origin + '/')
        if foundat == 0:
            return True

        if not api:
            return False

        allowed_origins = self.db.config['WEB_ALLOWED_API_ORIGINS']
        # find a match for other possible origins
        # Original spec says origin is case sensitive match.
        # Living spec doesn't address Origin value's case or
        # how to compare it. So implement case sensitive....
        if origin in allowed_origins:
            return True
        # Block use of * when origin match is used for
        # allowing credentials. See:
        # https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS
        # under Credentials Requests and Wildcards
        return (allowed_origins and allowed_origins[0] == '*'
                and not credentials)

    def is_referer_header_ok(self, api=False):
        referer = self.env['HTTP_REFERER']
        # parse referer and create an origin
        referer_comp = urllib_.urlparse(referer)

        # self.base always has trailing /, so add trailing / to referer_origin
        referer_origin = "%s://%s/" % (referer_comp[0], referer_comp[1])
        foundat = self.base.find(referer_origin)
        if foundat == 0:
            return True

        if not api:
            return False

        allowed_origins = self.db.config['WEB_ALLOWED_API_ORIGINS']
        if allowed_origins and allowed_origins[0] == '*':
            return True

        # For referer, loop over allowed_api_origins and
        # see if any of them are a prefix to referer, case sensitive.
        # Append / to each origin so that:
        # an allowed_origin of https://my.host does not match
        # a referer of https://my.host.com/my/path
        for allowed_origin in allowed_origins:
            foundat = referer_origin.find(allowed_origin + '/')
            if foundat == 0:
                return True
        return False

    def handle_csrf(self, api=False):
        '''Handle csrf token lookup and validate current user and session

            This implements (or tries to implement) the
            Session-Dependent Nonce from
            https://seclab.stanford.edu/websec/csrf/csrf.pdf.

            Changing this to an HMAC(sessionid,secret) will
            remove the need for saving a fair amount of
            state on the server (one nonce per form per
            page). If you have multiple forms/page this can
            lead to abandoned csrf tokens that have to time
            out and get cleaned up. But you lose per form
            tokens which may be an advantage. Also the HMAC
            is constant for the session, so provides more
            occasions for it to be exposed.

            This only runs on post (or put and delete for
            future use).  Nobody should be changing data
            with a get.

            A session token lifetime is settable in
            config.ini.  A future enhancement to the
            creation routines should allow for the requester
            of the token to set the lifetime.

            The unique session key and user id is stored
            with the token. The token is valid if the stored
            values match the current client's userid and
            session.

            If a user logs out, the csrf keys are
            invalidated since no other connection should
            have the same session id.

            At least to start I am reporting anti-csrf to
            the user.  If it's an attacker who can see the
            site, they can see the @csrf fields and can
            probably figure out that he needs to supply
            valid headers. Or they can just read this code
            8-).  So hiding it doesn't seem to help but it
            does arguably show the enforcement settings, but
            given the newness of this code notifying the
            user and having them notify the admins for
            debugging seems to be an advantage.

        '''
        # Create the otks handle here as we need it almost immediately.
        # If this is perf issue, set to None here and check below
        # once all header checks have passed if it needs to be opened.
        otks = self.db.getOTKManager()

        # Assume: never allow changes via GET
        if self.env['REQUEST_METHOD'] not in ['POST', 'PUT', 'DELETE']:
            if (self.form.list is not None) and ("@csrf" in self.form):
                # We have a nonce being used with a method it should
                # not be. If the nonce exists, report to admin so they
                # can fix the nonce leakage and destroy it. (nonces
                # used in a get are more exposed than those used in a
                # post.) Note, I don't attempt to validate here since
                # existence here is the sign of a failure.  If nonce
                # exists try to report the referer header to try to
                # find where this comes from so it can be fixed.  If
                # nonce doesn't exist just ignore it. Maybe we should
                # report, but somebody could spam us with a ton of
                # invalid keys and fill up the logs.
                if 'HTTP_REFERER' in self.env:
                    referer = self.env['HTTP_REFERER']
                else:
                    referer = self._("Referer header not available.")
                key = self.form['@csrf'].value
                if otks.exists(key):
                    logger.error(
                        self._("csrf key used with wrong method from: %s"),
                        referer)
                    otks.destroy(key)
                    otks.commit()
            # do return here. Keys have been obsoleted.
            # we didn't do a expire cycle of session keys,
            # but that's ok.
            return True

        config = self.instance.config
        current_user = self.db.getuid()

        # List HTTP headers we check. Note that the xmlrpc header is
        # missing. Its enforcement is different (yes/required are the
        # same for example) so we don't include here.
        header_names = [
            "ORIGIN",
            "REFERER",
            "X-FORWARDED-HOST",
            "HOST",
            ]

        header_pass = 0  # count of passing header checks

        # If required headers are missing, raise an error
        for header in header_names:
            if (config["WEB_CSRF_ENFORCE_HEADER_%s" % header] == 'required'
                    and "HTTP_%s" % header.replace('-', '_') not in self.env):
                logger.error(self._(
                    ''"csrf header %(header)s required but missing "
                    ''"for user%(userid)s.") % {
                        'header': header,
                        'userid': current_user})
                raise Unauthorised(self._("Missing header: %s") % header)

        # self.base always matches: ^https?://hostname
        enforce = config['WEB_CSRF_ENFORCE_HEADER_REFERER']
        if 'HTTP_REFERER' in self.env and enforce != "no":
            if not self.is_referer_header_ok(api=api):
                referer = self.env['HTTP_REFERER']
                logmsg = self._(
                    ''"csrf Referer header check failed for user%(userid)s. "
                    ''"Value=%(referer)s") % {'userid': current_user,
                                              'referer': referer}
                if enforce in ('required', 'yes'):
                    logger.error(logmsg)
                    raise Unauthorised(self._("Invalid Referer: %s") % (
                        referer))
                if enforce == 'logfailure':
                    logger.warning(logmsg)
            else:
                header_pass += 1

        # if you change these make sure to consider what
        # happens if header variable exists but is empty.
        # self.base.find("") returns 0 for example not -1
        enforce = config['WEB_CSRF_ENFORCE_HEADER_ORIGIN']
        if 'HTTP_ORIGIN' in self.env and enforce != "no":
            if not self.is_origin_header_ok(api=api):
                origin = self.env['HTTP_ORIGIN']
                logmsg = self._(
                    ''"csrf Origin header check failed for user%(userid)s. "
                    ''"Value=%(origin)s") % {
                        'userid': current_user, 'origin': origin}
                if enforce in ('required', 'yes'):
                    logger.error(logmsg)
                    raise Unauthorised(self._("Invalid Origin %s" % origin))
                if enforce == 'logfailure':
                    logger.warning(logmsg)
            else:
                header_pass += 1

        enforce = config['WEB_CSRF_ENFORCE_HEADER_X-FORWARDED-HOST']
        if 'HTTP_X_FORWARDED_HOST' in self.env:
            if enforce != "no":
                host = self.env['HTTP_X_FORWARDED_HOST']
                foundat = self.base.find('://' + host + '/')
                # 4 means self.base has http:/ prefix, 5 means https:/ prefix
                if foundat not in [4, 5]:
                    logmsg = self._(
                        ''"csrf X-FORWARDED-HOST header check failed "
                        ''"for user%(userid)s. Value=%(host)s") % {
                            'userid': current_user, 'host': host}
                    if enforce in ('required', 'yes'):
                        logger.error(logmsg)
                        raise Unauthorised(self._(
                            "Invalid X-FORWARDED-HOST %s") % host)
                    if enforce == 'logfailure':
                        logger.warning(logmsg)
                else:
                    header_pass += 1
        else:
            # https://seclab.stanford.edu/websec/csrf/csrf.pdf
            # recommends checking HTTP HOST header as well.
            # If there is an X-FORWARDED-HOST header, check
            # that only. The proxy setting X-F-H has probably set
            # the host header to a local hostname that is
            # internal name of system not name supplied by user.
            enforce = config['WEB_CSRF_ENFORCE_HEADER_HOST']
            if 'HTTP_HOST' in self.env and enforce != "no":
                host = self.env['HTTP_HOST']
                foundat = self.base.find('://' + host + '/')
                # 4 means http:// prefix, 5 means https:// prefix
                if foundat not in [4, 5]:
                    logmsg = self._(
                        ''"csrf HOST header check failed for "
                        ''"user%(userid)s. Value=%(host)s") % {
                            'userid': current_user, 'host': host}
                    if enforce in ('required', 'yes'):
                        logger.error(logmsg)
                        raise Unauthorised(self._("Invalid HOST %s") % host)
                    if enforce == 'logfailure':
                        logger.warning(logmsg)
                else:
                    header_pass += 1

        enforce = config['WEB_CSRF_HEADER_MIN_COUNT']
        if header_pass < enforce:
            logger.error(self._("Csrf: unable to verify sufficient headers"))
            raise UsageError(self._("Unable to verify sufficient headers"))

        enforce = config['WEB_CSRF_ENFORCE_HEADER_X-REQUESTED-WITH']
        if api and enforce in ['required', 'yes']:
            # if we get here we have usually passed at least one
            # header check. We check for presence of this custom
            # header for xmlrpc/rest calls only.
            # E.G. X-Requested-With: XMLHttpRequest
            # Note we do not use CSRF nonces for xmlrpc/rest requests.
            #
            # see: https://www.owasp.org/index.php/Cross-Site_Request_Forgery_(CSRF)_Prevention_Cheat_Sheet#Protecting_REST_Services:_Use_of_Custom_Request_Headers
            if 'HTTP_X_REQUESTED_WITH' not in self.env:
                logger.error(self._(
                    ''"csrf X-REQUESTED-WITH xmlrpc required header "
                    ''"check failed for user%(userid)s."),
                    {"userid": current_user})
                raise UsageError(self._("Required Header Missing"))

        # Expire old csrf tokens now so we don't use them.  These will
        # be committed after the otks.destroy below.  Note that the
        # self.clean_up run as part of determine_user() will run only
        # once an hour. If we have short lived (e.g. 5 minute) keys
        # they will live too long if we depend on clean_up. So we do
        # our own.
        otks.clean()

        if api:
            # Save removal of expired keys from database.
            otks.commit()
            # Return from here since we have done housekeeping
            # and don't use csrf tokens for xmlrpc.
            return True

        # process @csrf tokens past this point.
        key = None
        nonce_user = None
        nonce_session = None

        if '@csrf' in self.form:
            key = self.form['@csrf'].value

            nonce_user = otks.get(key, 'uid', default=None)
            nonce_session = otks.get(key, 'sid', default=None)
            # The key has been used or compromised.
            # Delete it to prevent replay.
            otks.destroy(key)

        # commit the deletion/expiration of all keys
        otks.commit()

        enforce = config['WEB_CSRF_ENFORCE_TOKEN']
        if key is None:  # we do not have an @csrf token
            if enforce == 'required':
                logger.error(self._(
                    "Required csrf field missing for user%(userid)s"),
                             {"userid": current_user})
                raise UsageError(self._(
                    ''"We can't validate your session (csrf failure). "
                    ''"Re-enter any unsaved data and try again."))
            if enforce == 'logfailure':
                # FIXME include url
                logger.warning(self._(
                    "csrf field not supplied by user%(userid)s"),
                    {"userid": current_user})
            else:
                # enforce is either yes or no. Both permit change if token is
                # missing
                return True

        current_session = self.session_api._sid

        # validate against user and session
        if current_user != nonce_user:
            logmsg = self._(
                ''"Csrf mismatch user: current user %(user)s != stored "
                ''"user %(stored)s, current session, stored session: "
                ''"%(cur_sess)s,%(stor_sess)s for key %(key)s.") % {
                    'user': current_user,
                    'stored': nonce_user,
                    'cur_sess': current_session,
                    'stor_sess': nonce_session,
                    'key': key}
            if enforce in ('required', 'yes'):
                logger.error(logmsg)
                raise UsageError(self._(
                    ''"We can't validate your session (csrf failure). "
                    ''"Re-enter any unsaved data and try again."))
            if enforce == 'logfailure':
                logger.warning(logmsg)

        if current_session != nonce_session:
            logmsg = self._(
                ''"Csrf mismatch user: current session %(curr_sess)s "
                ''"!= stored session %(stor_sess)s, current user/stored "
                ''"user is: %(user)s for key %(key)s.") % {
                    'curr_sess': current_session,
                    'stor_sess': nonce_session,
                    'user': current_user,
                    'key': key}
            if enforce in ('required', 'yes'):
                logger.error(logmsg)
                raise UsageError(self._(
                    ''"We can't validate your session (csrf failure). "
                    ''"Re-enter any unsaved data and try again."))
            if enforce == 'logfailure':
                logger.warning(logmsg)

        # we are done and the change can occur.
        return True

    def opendb(self, username):
        """Open the database and set the current user.

        Opens a database once. On subsequent calls only the user is set on
        the database object the instance.optimize is set. If we are in
        "Development Mode" (cf. roundup_server) then the database is always
        re-opened.
        """
        # don't do anything if the db is open and the user has not changed
        if hasattr(self, 'db') and self.db.isCurrentUser(username):
            return

        # open the database or only set the user
        if not hasattr(self, 'db'):
            self.db = self.instance.open(username)
        elif self.instance.optimize:
                self.db.setCurrentUser(username)
        else:
            self.db.close()
            self.db = self.instance.open(username)
            # The old session API refers to the closed database;
            # we can no longer use it.
            self.session_api = Session(self)

        self.db.tx_Source = "web"

    # match designator in URL stripping leading 0's. So:
    # https://issues.roundup-tracker.org/issue002551190 is the same as
    # https://issues.roundup-tracker.org/issue2551190
    # Note: id's are strings not numbers so "02" != "2" but 02 == 2
    dre_url = re.compile(r'([^\d]+)0*(\d+)')

    def determine_context(self, dre=dre_url):
        """Determine the context of this page from the URL:

        The URL path after the instance identifier is examined. The path
        is generally only one entry long.

        - if there is no path, then we are in the "home" context.
        - if the path is "_file", then the additional path entry
          specifies the filename of a static file we're to serve up
          from the instance "html" directory. Raises a SendStaticFile
          exception.(*)
        - if there is something in the path (eg "issue"), it identifies
          the tracker class we're to display.
        - if the path is an item designator (eg "issue123"), then we're
          to display a specific item.
        - if the path starts with an item designator and is longer than
          one entry, then we're assumed to be handling an item of a
          FileClass, and the extra path information gives the filename
          that the client is going to label the download with (ie
          "file123/image.png" is nicer to download than "file123"). This
          raises a SendFile exception.(*)

        Both of the "*" types of contexts stop before we bother to
        determine the template we're going to use. That's because they
        don't actually use templates.

        The template used is specified by the :template CGI variable,
        which defaults to:

        - only classname suplied:          "index"
        - full item designator supplied:   "item"

        We set:

             self.classname  - the class to display, can be None

             self.template   - the template to render the current context with

             self.nodeid     - the nodeid of the class we're displaying
        """
        # default the optional variables
        self.classname = None
        self.nodeid = None

        # see if a template or messages are specified
        template_override = ok_message = error_message = None
        try:
            keys = self.form.keys()
        except TypeError:
            keys = ()
        for key in keys:
            if self.FV_TEMPLATE.match(key):
                template_override = self.form[key].value
            elif self.FV_OK_MESSAGE.match(key):
                ok_message = self.form[key].value
            elif self.FV_ERROR_MESSAGE.match(key):
                error_message = self.form[key].value

        # see if we were passed in a message
        if ok_message:
            self.add_ok_message(ok_message)
        if error_message:
            self.add_error_message(error_message)

        # determine the classname and possibly nodeid
        path = self.path.split('/')
        if not path or path[0] in ('', 'home', 'index'):
            if template_override is not None:
                self.template = template_override
            else:
                self.template = ''
            return
        if path[0] in ('_file', '@@file'):
            raise SendStaticFile(os.path.join(*path[1:]))

        self.classname = path[0]
        if len(path) > 1:
            # send the file identified by the designator in path[0]
            raise SendFile(path[0])

        # see if we got a designator
        m = dre.match(self.classname)
        if m:
            self.classname = m.group(1)
            self.nodeid = m.group(2)
            try:
                klass = self.db.getclass(self.classname)
            except KeyError:
                raise NotFound('%s/%s' % (self.classname, self.nodeid))
            if int(self.nodeid) > 2**31:
                # Postgres will complain with a ProgrammingError
                # if we try to pass in numbers that are too large
                raise NotFound('%s/%s' % (self.classname, self.nodeid))
            if not klass.hasnode(self.nodeid):
                raise NotFound('%s/%s' % (self.classname, self.nodeid))
            # with a designator, we default to item view
            self.template = 'item'
        else:
            # with only a class, we default to index view
            self.template = 'index'

        # make sure the classname is valid
        try:
            self.db.getclass(self.classname)
        except KeyError:
            raise NotFound(self.classname)

        # see if we have a template override
        if template_override is not None:
            self.template = template_override

    # re for splitting designator, see also dre_url above this one
    # doesn't strip leading 0's from the id. Why not??
    dre = re.compile(r'([^\d]+)(\d+)')

    def serve_file(self, designator, dre=dre):
        """ Serve the file from the content property of the designated item.
        """
        m = dre.match(str(designator))
        if not m:
            raise NotFound(str(designator))
        classname, nodeid = m.group(1), m.group(2)

        try:
            klass = self.db.getclass(classname)
        except KeyError:
            # The classname was not valid.
            raise NotFound(str(designator))

        # perform the Anonymous user access check
        self.check_anonymous_access()

        # make sure we have the appropriate properties
        props = klass.getprops()
        if 'type' not in props:
            raise NotFound(designator)
        if 'content' not in props:
            raise NotFound(designator)

        # make sure we have permission
        if not self.db.security.hasPermission('View', self.userid,
                                              classname, 'content', nodeid):
            raise Unauthorised(self._("You are not allowed to view "
                                      "this file."))

        # --- mime-type security
        # mime type detection is performed in cgi.form_parser

        if self.instance.config['WEB_ALLOW_HTML_FILE']:
            self.mime_type_allowlist.append('text/html')

        try:
            mime_type = klass.get(nodeid, 'type')
        except IndexError as e:
            raise NotFound(e)
        # Can happen for msg class:
        if not mime_type:
            mime_type = 'text/plain'

        if mime_type not in self.mime_type_allowlist:
            mime_type = 'application/octet-stream'

        # --/ mime-type security

        # If this object is a file (i.e., an instance of FileClass),
        # see if we can find it in the filesystem.  If so, we may be
        # able to use the more-efficient request.sendfile method of
        # sending the file.  If not, just get the "content" property
        # in the usual way, and use that.
        content = None
        filename = None
        if isinstance(klass, hyperdb.FileClass):
            try:
                filename = self.db.filename(classname, nodeid)
            except AttributeError:
                # The database doesn't store files in the filesystem
                # and therefore doesn't provide the "filename" method.
                pass
            except IOError:
                # The file does not exist.
                pass
        if not filename:
            content = klass.get(nodeid, 'content')

        lmt = klass.get(nodeid, 'activity').timestamp()

        self._serve_file(lmt, None, mime_type, content, filename)

    def serve_static_file(self, file):
        """ Serve up the file named from the templates dir
        """
        # figure the filename - try STATIC_FILES, then TEMPLATES dir
        for dir_option in ('STATIC_FILES', 'TEMPLATES'):
            prefix = self.instance.config[dir_option]
            if not prefix:
                continue
            if is_us(prefix):
                # prefix can be a string or list depending on
                # option. Make it a list to iterate over.
                prefix = [prefix]

            for p in prefix:
                # if last element of STATIC_FILES ends with '/-',
                # or \- on windows, we failed to find the file
                # and should not look in TEMPLATES. So raise exception.
                if (dir_option == 'STATIC_FILES' and p[-1:] == '-' and
                    p[-2:-1] in ('/', '\\')):
                    raise NotFound(file)

                # ensure the load doesn't try to poke outside
                # of the static files directory
                p = os.path.normpath(p)
                filename = os.path.normpath(os.path.join(p, file))
                if os.path.isfile(filename) and filename.startswith(p):
                    break  # inner loop over list of directories

                # reset filename to None as sentinel for use below.
                filename = None

            # break out of outer loop over options
            if filename:
                break

        if filename is None:  # we didn't find a filename
            raise NotFound(file)

        # detemine meta-type
        file = str(file)
        mime_type = mimetypes.guess_type(file)[0]
        if not mime_type:
            mime_type = 'text/css' if file.endswith('.css') else 'text/plain'

        # get filename: given a/b/c.js extract c.js
        fn = file.rpartition("/")[2]
        if fn in self.Cache_Control:
            # if filename matches, don't use cache control
            # for mime type.
            self.additional_headers['Cache-Control'] = \
                            self.Cache_Control[fn]
        elif mime_type in self.Cache_Control:
            self.additional_headers['Cache-Control'] = \
                            self.Cache_Control[mime_type]

        self._serve_file(None, None, mime_type, '', filename)

    def _serve_file(self, lmt, etag, mime_type, content=None, filename=None):
        """guts of serve_file() and serve_static_file()

            if lmt or etag are None, derive them from file filename.

            Handles if-modified-since and if-none-match etag
            conditional gets.

            It produces an raw etag header without encoding suffix.
            But it adds Accept-Encoding to the vary header.

        """
        if filename:
            stat_info = os.stat(filename)

            if lmt is None:
                # last-modified time
                lmt = stat_info[stat.ST_MTIME]
            if etag is None:
                # FIXME: maybe etag should depend on encoding.
                # it is an apache compatible etag without encoding.
                etag = '"%x-%x-%x"' % (stat_info[stat.ST_INO],
                                       stat_info[stat.ST_SIZE],
                                       stat_info[stat.ST_MTIME])

            # spit out headers for conditional request
            self.setHeader("ETag", etag)
            self.additional_headers['Last-Modified'] = \
                email.utils.formatdate(lmt, usegmt=True)

            inm = None
            # ETag is a more strict check than modified date. Use etag
            # check if available. Skip testing modified data.
            if hasattr(self.request, 'headers'):
                inm = self.request.headers.get('if-none-match')
            elif 'HTTP_IF_NONE_MATCH' in self.env:
                # maybe the cgi will put the header in the env var
                inm = self.env['HTTP_IF_NONE_MATCH']
            if inm and etag == inm:
                # because we can compress, always set Accept-Encoding
                # value. Otherwise caches can serve up the wrong info
                # if their cached copy has no compression.
                self.setVary("Accept-Encoding")
                '''
                to solve issue2551356 I may need to determine
                the content encoding.
                if (self.determine_content_encoding()):
                '''
                raise NotModified

            if self.if_not_modified_since(lmt):
                # because we can compress, always set Accept-Encoding
                # value. Otherwise caches can serve up the wrong info
                # if their cached copy has no compression.
                self.setVary("Accept-Encoding")
                '''
                  to solve issue2551356 I may need to determine
                  the content encoding.
                  if (self.determine_content_encoding()):
                '''
                raise NotModified

        # don't set until we are sure we are sending a response body.
        self.additional_headers['Content-Type'] = mime_type

        if filename:
            self.write_file(filename)
        else:
            self.additional_headers['Content-Length'] = str(len(content))
            self.write(content)

    def if_not_modified_since(self, lmt):
        ims = None
        # see if there's an if-modified-since...
        if hasattr(self.request, 'headers'):
            ims = self.request.headers.get('if-modified-since')
        elif 'HTTP_IF_MODIFIED_SINCE' in self.env:
            # cgi will put the header in the env var
            ims = self.env['HTTP_IF_MODIFIED_SINCE']

        if ims:
            datestamp = email.utils.parsedate(ims)
            if datestamp is not None:
                ims = datestamp[:6]
            else:
                # set to beginning of time so whole file will be sent
                ims = (0, 0, 0, 0, 0, 0)
            lmtt = time.gmtime(lmt)[:6]
            return lmtt <= ims

        return False

    def send_error_to_admin(self, subject, html, txt):
        """Send traceback information to admin via email.
           We send both, the formatted html (with more information) and
           the text version of the traceback. We use
           multipart/alternative so the receiver can chose which version
           to display.
        """
        to = [self.mailer.config.ADMIN_EMAIL]
        message = MIMEMultipart('alternative')
        self.mailer.set_message_attributes(message, to, subject)
        part = self.mailer.get_text_message('utf-8', 'html')
        part.set_payload(html, part.get_charset())
        message.attach(part)
        part = self.mailer.get_text_message()
        part.set_payload(txt, part.get_charset())
        message.attach(part)
        self.mailer.smtp_send(to, message.as_string())

    def renderFrontPage(self, message):
        """Return the front page of the tracker."""

        self.classname = self.nodeid = None
        self.template = ''
        self.add_error_message(message)
        self.write_html(self.renderContext())

    def selectTemplate(self, name, view):
        """ Choose existing template for the given combination of
            classname (name parameter) and template request variable
            (view parameter) and return its name.

            View can be a single template or two templates separated
            by a vbar '|' character.  If the Client object has a
            non-empty _error_message attribute, the right hand
            template (error template) will be used. If the
            _error_message is empty, the left hand template (ok
            template) will be used.

            In most cases the name will be "classname.view", but
            if "view" is None, then template name "classname" will
            be returned.

            If "classname.view" template doesn't exist, the
            "_generic.view" is used as a fallback.

            [ ] cover with tests
        """

        # determine if view is oktmpl|errortmpl. If so assign the
        # right one to the view parameter. If we don't have alternate
        # templates, just leave view alone.
        if (view and view.find('|') != -1):
            # we have alternate templates, parse them apart.
            (oktmpl, errortmpl) = view.split("|", 1)

            # Choose the right template
            view = errortmpl if self._error_message else oktmpl

        loader = self.instance.templates

        # if classname is not set, use "home" template
        if name is None:
            name = 'home'

        tplname = name
        if view:
            # Support subdirectories for templates. Value is path/to/VIEW
            # or just VIEW if the template is in the html directory of
            # the tracker.
            slash_loc = view.rfind("/")
            if slash_loc == -1:
                # try plain class.view
                tplname = '%s.%s' % (name, view)
            else:
                # try path/class.view
                tplname = '%s/%s.%s' % (
                    view[:slash_loc], name, view[slash_loc + 1:])

        if loader.check(tplname):
            return tplname

        # rendering class/context with generic template for this view.
        # with no view it's impossible to choose which generic template to use
        if not view:
            raise templating.NoTemplate('Template "%s" doesn\'t exist' % name)

        if slash_loc == -1:
            generic = '_generic.%s' % view
        else:
            generic = '%s/_generic.%s' % (view[:slash_loc], view[slash_loc + 1:])
        if loader.check(generic):
            return generic

        raise templating.NoTemplate(
            'No template file exists for templating '
            '"%s" with template "%s" (neither "%s" nor "%s")' % (
                name, view, tplname, generic))

    def renderContext(self):
        """ Return a PageTemplate for the named page
        """
        try:
            tplname = self.selectTemplate(self.classname, self.template)

            # catch errors so we can handle PT rendering errors more nicely
            args = {
                'ok_message': self._ok_message,
                'error_message': self._error_message,
            }
            pt = self.instance.templates.load(tplname)
            # let the template render figure stuff out
            try:
                result = pt.render(self, None, None, **args)
            except IndexerQueryError as e:
                result = self.renderError(e.args[0])
            except ExpressionError as e:
                self.add_error_message(str(e))
                self.template = "search"
                result = self.renderContext()

            if 'Content-Type' not in self.additional_headers:
                self.additional_headers['Content-Type'] = pt.content_type
            if self.env.get('CGI_SHOW_TIMING', ''):
                if self.env['CGI_SHOW_TIMING'].upper() == 'COMMENT':
                    timings = {'starttag': '<!-- ', 'endtag': ' -->'}
                else:
                    timings = {'starttag': '<p>', 'endtag': '</p>'}
                timings['seconds'] = time.time() - self.start
                s = self._(
                    '%(starttag)sTime elapsed: %(seconds)fs%(endtag)s\n'
                ) % timings
                if hasattr(self.db, 'stats'):
                    timings.update(self.db.stats)
                    s += self._("%(starttag)sCache hits: %(cache_hits)d,"
                                " misses %(cache_misses)d."
                                " Loading items: %(get_items)f secs."
                                " Filtering: %(filtering)f secs."
                                "%(endtag)s\n") % timings
                s += '</body>'
                result = result.replace('</body>', s)
            return result
        except templating.NoTemplate as message:
            self.response_code = 400
            return '<strong>%s</strong>' % html_escape(str(message))
        except templating.Unauthorised as message:
            raise Unauthorised(html_escape(str(message)))
        except Exception:
            # everything else
            if self.instance.config.WEB_DEBUG:
                return cgitb.pt_html(i18n=self.translator)
            exc_info = sys.exc_info()
            try:
                # If possible, send the HTML page template traceback
                # to the administrator.
                subject = "Templating Error: %s" % exc_info[1]
                self.send_error_to_admin(subject, cgitb.pt_html(), format_exc())
                # Now report the error to the user.
                return self._(default_err_msg)
            except Exception:
                # Reraise the original exception.  The user will
                # receive an error message, and the adminstrator will
                # receive a traceback, albeit with less information
                # than the one we tried to generate above.
                if sys.version_info[0] > 2:
                    raise exc_info[0](exc_info[1]).with_traceback(exc_info[2])
                exec('raise exc_info[0], exc_info[1], exc_info[2]')  # nosec

    def renderError(self, error, response_code=400, use_template=True):
        self.response_code = response_code

        # see if error message already logged add if not
        if error not in self._error_message:
            self.add_error_message(error, escape=True)

        # allow use of template for a specific code
        trial_templates = []
        if use_template:
            if response_code == 400:
                trial_templates = ["400"]
            else:
                trial_templates = [str(response_code), "400"]

        tplname = None
        for rcode in trial_templates:
            try:
                tplname = self.selectTemplate(self.classname, rcode)
                break
            except templating.NoTemplate:
                pass

        if not tplname:
            # call string of serious error to get basic html
            # response.
            return str(SeriousError(error))

        args = {
            'ok_message': self._ok_message,
            'error_message': self._error_message,
        }

        try:
            pt = self.instance.templates.load(tplname)
            return pt.render(self, None, None, **args)
        except Exception:
            # report original error
            return str(SeriousError(error))

    # these are the actions that are available
    actions = (
        ('edit',        actions.EditItemAction),  # noqa: E241
        ('editcsv',     actions.EditCSVAction),  # noqa: E241
        ('new',         actions.NewItemAction),  # noqa: E241
        ('register',    actions.RegisterAction),  # noqa: E241
        ('confrego',    actions.ConfRegoAction),  # noqa: E241
        ('passrst',     actions.PassResetAction),  # noqa: E241
        ('login',       actions.LoginAction),  # noqa: E241
        ('logout',      actions.LogoutAction),  # noqa: E241
        ('search',      actions.SearchAction),  # noqa: E241
        ('restore',     actions.RestoreAction),  # noqa: E241
        ('retire',      actions.RetireAction),  # noqa: E241
        ('show',        actions.ShowAction),  # noqa: E241
        ('export_csv',  actions.ExportCSVAction),  # noqa: E241
        ('export_csv_id',  actions.ExportCSVWithIdAction),  # noqa: E241
    )

    def handle_action(self):
        """ Determine whether there should be an Action called.

            The action is defined by the form variable :action which
            identifies the method on this object to call. The actions
            are defined in the "actions" sequence on this class.

            Actions may return a page (by default HTML) to return to the
            user, bypassing the usual template rendering.

            We explicitly catch Reject and ValueError exceptions and
            present their messages to the user.
        """
        action = None
        try:
            if ':action' in self.form:
                action = self.form[':action']
            elif '@action' in self.form:
                action = self.form['@action']
        except TypeError:
            pass
        if action is None:
            return None

        if isinstance(action, list):
            raise SeriousError(
                self._('broken form: multiple @action values submitted'))

        action = action.value.lower()

        try:
            action_klass = self.get_action_class(action)

            # call the mapped action
            if isinstance(action_klass, type('')):
                # old way of specifying actions
                return getattr(self, action_klass)()

            return action_klass(self).execute()
        except (ValueError, Reject) as err:
            escape = not isinstance(err, RejectRaw)
            self.add_error_message(str(err), escape=escape)

    def get_action_class(self, action_name):
        if (hasattr(self.instance, 'cgi_actions') and
                action_name in self.instance.cgi_actions):
            # tracker-defined action
            action_klass = self.instance.cgi_actions[action_name]
        else:
            # go with a default, action_klass used after end of loop
            for name, action_klass in self.actions:  # noqa: B007
                if name == action_name:
                    break
            else:
                raise ValueError('No such action "%s"' %
                                 html_escape(action_name))
        return action_klass

    def _socket_op(self, call, *args, **kwargs):
        """Execute socket-related operation, catch common network errors

        Parameters:
            call: a callable to execute
            args, kwargs: call arguments

        """
        try:
            call(*args, **kwargs)
        except socket.error as err:
            err_errno = getattr(err, 'errno', None)
            if err_errno is None:
                try:
                    err_errno = err[0]
                except TypeError:
                    pass
            if err_errno not in self.IGNORE_NET_ERRORS:
                raise
        except IOError:
            # Apache's mod_python will raise IOError -- without an
            # accompanying errno -- when a write to the client fails.
            # A common case is that the client has closed the
            # connection.  There's no way to be certain that this is
            # the situation that has occurred here, but that is the
            # most likely case.
            pass

    def determine_content_encoding(self, list_all=False, precompressed=False):

        encoding_list = []

        # FIXME: Should parse for q= values and properly order
        # the request encodings. Also should handle identity coding.
        # Then return first acceptable by q value.
        # This code always uses order: zstd, br, gzip. It will send identity
        #  even if identity excluded rather than returning 406.
        accept_encoding = self.request.headers.get('accept-encoding') or []

        if accept_encoding:
            for enc in ['zstd', 'br', 'gzip']:
                if ((enc in self.compressors) or precompressed) and \
                   (enc in accept_encoding):
                    if not list_all:
                        return enc

                    encoding_list.append(enc)

        # Return value must evaluate to false in boolean context if no
        # acceptable encoding is found. If an (non-identity) encoding
        # is found the Vary header will include accept-encoding.
        # What to return if the identity encoding is unacceptable?
        #   Maybe raise a 406 from here?
        if not list_all:
            return None
        return encoding_list

    def setVary(self, header):
        '''Vary header will include the new header. This will append
           if Vary exists.'''

        if ('Vary' in self.additional_headers and
            header not in self.additional_headers['Vary']):
            self.additional_headers['Vary'] += ", %s" % header
        else:
            self.additional_headers['Vary'] = header

    def compress_encode(self, byte_content, quality=4):

        if not self.instance.config.WEB_DYNAMIC_COMPRESSION:
            # dynamic compression disabled.
            return byte_content

        # don't compress small content
        if len(byte_content) < 100:
            return byte_content

        # abort if already encoded (e.g. served from
        # precompressed file or cache on disk)
        if ('Content-Encoding' in self.additional_headers):
            # Vary: 'Accept-Encoding' is set when Content-encoding set
            return byte_content

        # abort if file-type already compressed
        if ('Content-Type' in self.additional_headers) and \
           (self.additional_headers['Content-Type'] in
                self.precompressed_mime_types):
            return byte_content

        self.setVary('Accept-Encoding')

        encoder = None
        # return same content if unable to compress
        new_content = byte_content

        encoder = self.determine_content_encoding()

        if encoder == 'zstd':
            new_content = self.zstd.ZSTD_compress(byte_content, 3)
        elif encoder == 'br':
            # lgblock=0 sets value from quality
            new_content = self.brotli.compress(byte_content,
                                               quality=quality,
                                               mode=1,
                                               lgblock=0)
        elif encoder == 'gzip':
            try:
                new_content = self.gzip.compress(byte_content, compresslevel=5)
            except AttributeError:
                try:
                    from StringIO import cStringIO as IOBuff
                except ImportError:
                    # python 3
                    # however this code should not be needed under python3
                    # since py3 gzip library has compress() method.
                    from io import BytesIO as IOBuff

                out = IOBuff()
                # handle under python2
                f = self.gzip.GzipFile(fileobj=out, mode='w', compresslevel=5)
                f.write(byte_content)
                f.close()
                new_content = out.getvalue()

        if encoder:
            # we changed the data, change existing content-length header
            # and add Content-Encoding and Vary header.
            self.additional_headers['Content-Length'] = str(len(new_content))
            self.additional_headers['Content-Encoding'] = encoder
            try:
                current_etag = self.additional_headers['ETag']
            except KeyError:
                pass  # etag not set for non-rest endpoints
            else:
                etag_end = current_etag.rindex('"')
                self.additional_headers['ETag'] = (
                    current_etag[:etag_end] +
                    '-' + encoder + current_etag[etag_end:])

        return new_content

    def write(self, content):
        if not self.headers_done and self.env['REQUEST_METHOD'] != 'HEAD':
            # compress_encode modifies headers, must run before self.header()
            content = self.compress_encode(bs2b(content))

        if not self.headers_done:
            self.header()
        if self.env['REQUEST_METHOD'] != 'HEAD':
            self._socket_op(self.request.wfile.write, content)

    def write_html(self, content):
        if sys.version_info[0] > 2:
            # An action setting appropriate headers for a non-HTML
            # response may return a bytes object directly.
            if not isinstance(content, bytes):
                content = content.encode(self.charset, 'xmlcharrefreplace')
        elif self.charset != self.STORAGE_CHARSET:
            # recode output
            content = content.decode(self.STORAGE_CHARSET, 'replace')
            content = content.encode(self.charset, 'xmlcharrefreplace')

        if self.env['REQUEST_METHOD'] != 'HEAD' and not self.headers_done:
            # compress_encode modifies headers, must run before self.header()
            content = self.compress_encode(bs2b(content))

        if not self.headers_done:
            # at this point, we are sure about Content-Type
            if 'Content-Type' not in self.additional_headers:
                self.additional_headers['Content-Type'] = \
                    'text/html; charset=%s' % self.charset
            if 'Content-Length' not in self.additional_headers:
                self.additional_headers['Content-Length'] = str(len(content))
            self.header()

        if self.env['REQUEST_METHOD'] == 'HEAD':
            # client doesn't care about content
            return

        # and write
        self._socket_op(self.request.wfile.write, content)

    def http_strip(self, content):
        """Remove HTTP Linear White Space from 'content'.

        'content' -- A string.

        returns -- 'content', with all leading and trailing LWS
        removed."""

        # RFC 2616 2.2: Basic Rules
        #
        # LWS = [CRLF] 1*( SP | HT )
        return content.strip(" \r\n\t")

    def http_split(self, content):
        """Split an HTTP list.

        'content' -- A string, giving a list of items.

        returns -- A sequence of strings, containing the elements of
        the list."""

        # RFC 2616 2.1: Augmented BNF
        #
        # Grammar productions of the form "#rule" indicate a
        # comma-separated list of elements matching "rule".  LWS
        # is then removed from each element, and empty elements
        # removed.

        # Split at commas.
        elements = content.split(",")
        # Remove linear whitespace at either end of the string.
        elements = [self.http_strip(e) for e in elements]
        # Remove any now-empty elements.
        return [e for e in elements if e]

    def handle_range_header(self, length, etag):
        """Handle the 'Range' and 'If-Range' headers.

        'length' -- the length of the content available for the
        resource.

        'etag' -- the entity tag for this resources.

        returns -- If the request headers (including 'Range' and
        'If-Range') indicate that only a portion of the entity should
        be returned, then the return value is a pair '(offfset,
        length)' indicating the first byte and number of bytes of the
        content that should be returned to the client.  In addition,
        this method will set 'self.response_code' to indicate Partial
        Content.  In all other cases, the return value is 'None'.  If
        appropriate, 'self.response_code' will be
        set to indicate 'REQUESTED_RANGE_NOT_SATISFIABLE'.  In that
        case, the caller should not send any data to the client."""

        # RFC 2616 14.35: Range
        #
        # See if the Range header is present.
        ranges_specifier = self.env.get("HTTP_RANGE")
        if ranges_specifier is None:
            return None
        # RFC 2616 14.27: If-Range
        #
        # Check to see if there is an If-Range header.
        # Because the specification says:
        #
        #  The If-Range header ... MUST be ignored if the request
        #  does not include a Range header, we check for If-Range
        #  after checking for Range.
        if_range = self.env.get("HTTP_IF_RANGE")
        if if_range:
            # The grammar for the If-Range header is:
            #
            #   If-Range = "If-Range" ":" ( entity-tag | HTTP-date )
            #   entity-tag = [ weak ] opaque-tag
            #   weak = "W/"
            #   opaque-tag = quoted-string
            #
            # We only support strong entity tags.
            if_range = self.http_strip(if_range)
            if (not if_range.startswith('"')
                    or not if_range.endswith('"')):
                return None
            # If the condition doesn't match the entity tag, then we
            # must send the client the entire file.
            if if_range != etag:
                return None
        # The grammar for the Range header value is:
        #
        #   ranges-specifier = byte-ranges-specifier
        #   byte-ranges-specifier = bytes-unit "=" byte-range-set
        #   byte-range-set = 1#( byte-range-spec | suffix-byte-range-spec )
        #   byte-range-spec = first-byte-pos "-" [last-byte-pos]
        #   first-byte-pos = 1*DIGIT
        #   last-byte-pos = 1*DIGIT
        #   suffix-byte-range-spec = "-" suffix-length
        #   suffix-length = 1*DIGIT
        #
        # Look for the "=" separating the units from the range set.
        specs = ranges_specifier.split("=", 1)
        if len(specs) != 2:
            return None
        # Check that the bytes-unit is in fact "bytes".  If it is not,
        # we do not know how to process this range.
        bytes_unit = self.http_strip(specs[0])
        if bytes_unit != "bytes":
            return None
        # Seperate the range-set into range-specs.
        byte_range_set = self.http_strip(specs[1])
        byte_range_specs = self.http_split(byte_range_set)
        # We only handle exactly one range at this time.
        if len(byte_range_specs) != 1:
            return None
        # Parse the spec.
        byte_range_spec = byte_range_specs[0]
        pos = byte_range_spec.split("-", 1)
        if len(pos) != 2:
            return None
        # Get the first and last bytes.
        first = self.http_strip(pos[0])
        last = self.http_strip(pos[1])
        # We do not handle suffix ranges.
        #   Note this also captures atempts to make first
        #   element of range a negative number.
        if not first:
            return None
        # Convert the first and last positions to integers.
        try:
            first = int(first)
            if last:
                last = int(last)
            else:
                last = length - 1
        except ValueError:
            # The positions could not be parsed as integers.
            return None
        # Check that the range makes sense.
        # Note, if range is -1-10, first = '', so this code will never
        # be reached. if range = 1--10, this code is reached.
        if (first < 0 or last < 0 or last < first):
            return None
        if last >= length:
            # RFC 2616 10.4.17: 416 Requested Range Not Satisfiable
            #
            # If there is an If-Range header, RFC 2616 says that we
            # should just ignore the invalid Range header.
            if if_range:
                return None
            # Return code 416 with a Content-Range header giving the
            # allowable range.
            self.response_code = http_.client.REQUESTED_RANGE_NOT_SATISFIABLE
            self.setHeader("Content-Range", "bytes */%d" % length)
            return None
        # RFC 2616 10.2.7: 206 Partial Content
        #
        # Tell the client that we are honoring the Range request by
        # indicating that we are providing partial content.
        self.response_code = http_.client.PARTIAL_CONTENT
        # RFC 2616 14.16: Content-Range
        #
        # Tell the client what data we are providing.
        #
        #   content-range-spec = byte-content-range-spec
        #   byte-content-range-spec = bytes-unit SP
        #                             byte-range-resp-spec "/"
        #                             ( instance-length | "*" )
        #   byte-range-resp-spec = (first-byte-pos "-" last-byte-pos)
        #                          | "*"
        #   instance-length      = 1 * DIGIT
        self.setHeader("Content-Range",
                       "bytes %d-%d/%d" % (first, last, length))
        return (first, last - first + 1)

    def write_file(self, filename):
        """Send the contents of 'filename' to the user.
           Send an acceptable pre-compressed version of the
           file if it is newer than the uncompressed version.
        """

        # Assume we will return the entire file.
        offset = 0

        # initalize length from uncompressed file
        stat_info = os.stat(filename)
        length = stat_info[stat.ST_SIZE]

        # Determine if we are sending a range. If so, compress
        # on the fly. Otherwise see if we have a suitable
        # pre-compressed/encoded file we can send.
        if not self.env.get("HTTP_RANGE"):
            # no range, search for file in list ordered
            # from best to worst alternative
            encoding_list = self.determine_content_encoding(list_all=True,
                                                            precompressed=True)
            if encoding_list and self.db.config.WEB_USE_PRECOMPRESSED_FILES:
                # do we need to search through list? If best is not
                # precompressed, on the fly compress with best?
                # by searching list we will respond with precompressed
                # 2nd best or worse.
                for encoder in encoding_list:
                    try:
                        trial_filename = '%s.%s' % (filename, encoder)
                        trial_stat_info = os.stat(trial_filename)
                        if stat_info[stat.ST_MTIME] > \
                           trial_stat_info[stat.ST_MTIME]:
                            # compressed file is obsolete
                            # don't use it
                            logger.warning(self._(
                                "Cache failure: "
                                "compressed file %(compressed)s is "
                                "older than its source file "
                                "%(filename)s" % {
                                    'filename': filename,
                                    'compressed': trial_filename}))

                            continue
                        filename = trial_filename
                        length = trial_stat_info[stat.ST_SIZE]
                        self.setHeader('Content-Encoding', encoder)
                        self.setVary('Accept-Encoding')
                        break
                    # except FileNotFoundError: py2/py3
                    # compatible version
                    except EnvironmentError as e:
                        if e.errno != errno.ENOENT:
                            raise

        # If the headers have not already been finalized,
        if not self.headers_done:
            # RFC 2616 14.19: ETag
            #
            # Compute the entity tag, in a format similar to that
            # used by Apache.
            #
            # Tag does *not* change with Content-Encoding.
            # Header 'Vary: Accept-Encoding' is returned with response.
            # RFC2616 section 13.32 discusses etag and references
            # section 14.44 (Vary header) as being applicable to etag.
            # Hence the intermediate proxy should/must match
            # Accept-Encoding and ETag to determine whether to return
            # a 304 or report cache miss and fetch from origin server.
            #
            # RFC 9110 8.8.3.3 shows a different strong entity tag
            # generated for gzip and non gzip replies.
            etag = '"%x-%x-%x"' % (stat_info[stat.ST_INO],
                                   length,
                                   stat_info[stat.ST_MTIME])
            self.setHeader("ETag", etag)

            inm = self.request.headers.get('If-None-Match')
            if (inm):
                inm_etags = inm.split(',')
                inm_etags = [tag.strip() for tag in inm_etags]
                if etag in inm_etags:
                    self.setHeader('ETag', etag)
                    self.setVary('Accept-Encoding')
                    raise NotModified

                # need to check for etag-compression_code:
                # a41932-8b5-664ce93d-zstd or a41932-8b5-664ce93d-gzip
                tag_prefix = etag[:-1] + '-'
                for inm_etag in inm_etags:
                    if inm_etag.startswith(tag_prefix):
                        self.setHeader('ETag', inm_etag)
                        self.setVary('Accept-Encoding')
                        raise NotModified

            # RFC 2616 14.5: Accept-Ranges
            #
            # Let the client know that we will accept range requests.
            self.setHeader("Accept-Ranges", "bytes")
            # RFC 2616 14.35: Range
            #
            # If there is a Range header, we may be able to avoid
            # sending the entire file.
            content_range = self.handle_range_header(length, etag)
            if content_range:
                offset, length = content_range
            # RFC 2616 14.13: Content-Length
            #
            # Tell the client how much data we are providing.
            self.setHeader("Content-Length", str(length))
        # If the client doesn't actually want the body, or if we are
        # indicating an invalid range.
        if (self.env['REQUEST_METHOD'] == 'HEAD'
                or self.response_code ==
                http_.client.REQUESTED_RANGE_NOT_SATISFIABLE):
            self.setHeader("Content-Length", "0")
            self.header()
            return
        # Use the optimized "sendfile" operation, if possible.
        if hasattr(self.request, "sendfile"):
            self.header()
            self._socket_op(self.request.sendfile, filename, offset, length)
            return
        # Fallback to the "write" operation.
        with open(filename, 'rb') as f:
            if offset:
                f.seek(offset)
            content = f.read(length)
        self.write(content)

    def setHeader(self, header, value):
        """Override or delete a header to be returned to the user's browser.
        """
        if value is None:
            try:
                del (self.additional_headers[header])
            except KeyError:
                pass
        else:
            self.additional_headers[header] = value

    def header(self, headers=None, response=None):
        """Put up the appropriate header.
        """
        if headers is None:
            headers = {'Content-Type': 'text/html; charset=utf-8'}
        if response is None:
            response = self.response_code

        # update with additional info
        headers.update(self.additional_headers)

        if headers.get('Content-Type', 'text/html') == 'text/html':
            headers['Content-Type'] = 'text/html; charset=utf-8'

        if response in [204, 304]:  # has no body so no content-type
            del (headers['Content-Type'])

        headers = list(headers.items())

        for ((path, name), (value, expire)) in self._cookies.items():
            cookie = "%s=%s; Path=%s;" % (name, value, path)
            if expire is not None:
                cookie += " expires=%s;" % get_cookie_date(expire)
            # mark as secure if https, see issue2550689
            if self.secure:
                cookie += " secure;"
            ssc = self.db.config['WEB_SAMESITE_COOKIE_SETTING']
            if ssc != "None":
                cookie += " SameSite=%s;" % ssc
            # prevent theft of session cookie, see issue2550689
            cookie += " HttpOnly;"
            headers.append(('Set-Cookie', cookie))

        self._socket_op(self.request.start_response, headers, response)

        self.headers_done = 1
        if self.debug:
            self.headers_sent = headers

    def add_cookie(self, name, value, expire=86400 * 365, path=None):
        """Set a cookie value to be sent in HTTP headers

        Parameters:
            name:
                cookie name
            value:
                cookie value
            expire:
                cookie expiration time (seconds).
                If value is empty (meaning "delete cookie"),
                expiration time is forced in the past
                and this argument is ignored.
                If None, the cookie will expire at end-of-session.
                If omitted, the cookie will be kept for a year.
            path:
                cookie path (optional)

        """
        if path is None:
            path = self.cookie_path
        if not value:
            expire = -1
        self._cookies[(path, name)] = (value, expire)

    def make_user_anonymous(self):
        """ Make us anonymous

            This method used to handle non-existence of the 'anonymous'
            user, but that user is mandatory now.
        """
        self.userid = self.db.user.lookup('anonymous')
        self.user = 'anonymous'

    def standard_message(self, to, subject, body, author=None):
        """Send a standard email message from Roundup.

        "to"      - recipients list
        "subject" - Subject
        "body"    - Message
        "author"  - (name, address) tuple or None for admin email

        Arguments are passed to the Mailer.standard_message code.
        """
        try:
            self.mailer.standard_message(to, subject, body, author)
        except MessageSendError as e:
            self.add_error_message(str(e))
            return 0
        return 1

    def parsePropsFromForm(self, create=0):
        return FormParser(self).parse(create=create)

# vim: set et sts=4 sw=4 :
