"""WWW request handler (also used in the stand-alone server).
"""
__docformat__ = 'restructuredtext'

import base64, binascii, cgi, codecs, mimetypes, os
import quopri, random, re, rfc822, stat, sys, time
import socket, errno
from traceback import format_exc

try:
    from OpenSSL.SSL import SysCallError
except ImportError:
    SysCallError = None

from roundup import roundupdb, date, hyperdb, password
from roundup.cgi import templating, cgitb, TranslationService
from roundup.cgi.actions import *
from roundup.exceptions import *
from roundup.cgi.exceptions import *
from roundup.cgi.form_parser import FormParser
from roundup.mailer import Mailer, MessageSendError, encode_quopri
from roundup.cgi import accept_language
from roundup import xmlrpc

from roundup.anypy.cookie_ import CookieError, BaseCookie, SimpleCookie, \
    get_cookie_date
from roundup.anypy.io_ import StringIO
from roundup.anypy import http_
from roundup.anypy import urllib_

from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email.MIMEMultipart import MIMEMultipart

def initialiseSecurity(security):
    '''Create some Permissions and Roles on the security object

    This function is directly invoked by security.Security.__init__()
    as a part of the Security object instantiation.
    '''
    p = security.addPermission(name="Web Access",
        description="User may access the web interface")
    security.addPermissionToRole('Admin', p)

    # doing Role stuff through the web - make sure Admin can
    # TODO: deprecate this and use a property-based control
    p = security.addPermission(name="Web Roles",
        description="User may manipulate user Roles through the web")
    security.addPermissionToRole('Admin', p)

def clean_message(msg):
    return cgi.escape (msg).replace ('\n', '<br />\n')

error_message = ''"""<html><head><title>An error has occurred</title></head>
<body><h1>An error has occurred</h1>
<p>A problem was encountered processing your request.
The tracker maintainers have been notified of the problem.</p>
</body></html>"""


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
        self._sid  = None

        self.client = client
        self.session_db = client.db.getSessionManager()

        # parse cookies for session id
        self.cookie_name = 'roundup_session_%s' % \
            re.sub('[^a-zA-Z]', '', client.instance.config.TRACKER_NAME)
        cookies = LiberalCookie(client.env.get('HTTP_COOKIE', ''))
        if self.cookie_name in cookies:
            if not self.session_db.exists(cookies[self.cookie_name].value):
                self._sid = None
                # remove old cookie
                self.client.add_cookie(self.cookie_name, None)
            else:
                self._sid = cookies[self.cookie_name].value
                self._data = self.session_db.getall(self._sid)

    def _gen_sid(self):
        """ generate a unique session key """
        while 1:
            s = '%s%s'%(time.time(), random.random())
            s = binascii.b2a_base64(s).strip()
            if not self.session_db.exists(s):
                break

        # clean up the base64
        if s[-1] == '=':
            if s[-2] == '=':
                s = s[:-2]
            else:
                s = s[:-1]
        return s

    def clean_up(self):
        """Remove expired sessions"""
        self.session_db.clean()

    def destroy(self):
        self.client.add_cookie(self.cookie_name, None)
        self._data = {}
        self.session_db.destroy(self._sid)
        self.client.db.commit()

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
            self.client.db.commit()

    def update(self, set_cookie=False, expire=None):
        """ update timestamp in db to avoid expiration

            if 'set_cookie' is True, set cookie with 'expire' seconds lifetime
            if 'expire' is None - session will be closed with the browser

            XXX the session can be purged within a week even if a cookie
                lifetime is longer
        """
        self.session_db.updateTimestamp(self._sid)
        self.client.db.commit()

        if set_cookie:
            self.client.add_cookie(self.cookie_name, self._sid, expire=expire)



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

    During the processing of a request, the following attributes are used:

    - "db"
    - "error_message" holds a list of error messages
    - "ok_message" holds a list of OK messages
    - "session" is deprecated in favor of session_api (XXX remove)
    - "session_api" is the interface to store data in session
    - "user" is the current user's name
    - "userid" is the current user's id
    - "template" is the current :template context
    - "classname" is the current class context name
    - "nodeid" is the current context item id

    User Identification:
     Users that are absent in session data are anonymous and are logged
     in as that user. This typically gives them all Permissions assigned to the
     Anonymous Role.

     Every user is assigned a session. "session_api" is the interface to work
     with session data.

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

    def __init__(self, instance, request, env, form=None, translator=None):
        # re-seed the random number generator
        random.seed()
        self.start = time.time()
        self.instance = instance
        self.request = request
        self.env = env
        self.setTranslator(translator)
        self.mailer = Mailer(instance.config)

        # save off the path
        self.path = env['PATH_INFO']

        # this is the base URL for this tracker
        self.base = self.instance.config.TRACKER_WEB

        # should cookies be secure?
        self.secure = self.base.startswith ('https')

        # check the tracker_we setting
        if not self.base.endswith('/'):
            self.base = self.base + '/'

        # this is the "cookie path" for this tracker (ie. the path part of
        # the "base" url)
        self.cookie_path = urllib_.urlparse(self.base)[2]
        # cookies to set in http responce
        # {(path, name): (value, expire)}
        self._cookies = {}

        # see if we need to re-parse the environment for the form (eg Zope)
        if form is None:
            self.form = cgi.FieldStorage(fp=request.rfile, environ=env)
        else:
            self.form = form

        # turn debugging on/off
        try:
            self.debug = int(env.get("ROUNDUP_DEBUG", 0))
        except ValueError:
            # someone gave us a non-int debug level, turn it off
            self.debug = 0

        # flag to indicate that the HTTP headers have been sent
        self.headers_done = 0

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
        try:
            if self.env.get('CONTENT_TYPE') == 'text/xml' and self.path == 'xmlrpc':
                self.handle_xmlrpc()
            else:
                self.inner_main()
        finally:
            if hasattr(self, 'db'):
                self.db.close()


    def handle_xmlrpc(self):

        # Pull the raw XML out of the form.  The "value" attribute
        # will be the raw content of the POST request.
        assert self.form.file
        input = self.form.value
        # So that the rest of Roundup can query the form in the
        # usual way, we create an empty list of fields.
        self.form.list = []

        # Set the charset and language, since other parts of
        # Roundup may depend upon that.
        self.determine_charset()
        self.determine_language()
        # Open the database as the correct user.
        self.determine_user()
        self.check_anonymous_access()

        # Call the appropriate XML-RPC method.
        handler = xmlrpc.RoundupDispatcher(self.db,
                                           self.instance.actions,
                                           self.translator,
                                           allow_none=True)
        output = handler.dispatch(input)

        self.setHeader("Content-Type", "text/xml")
        self.setHeader("Content-Length", str(len(output)))
        self.write(output)

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
        self.ok_message = []
        self.error_message = []
        try:
            self.determine_charset()
            self.determine_language()

            try:
                # make sure we're identified (even anonymously)
                self.determine_user()

                # figure out the context and desired content template
                self.determine_context()

                # if we've made it this far the context is to a bit of
                # Roundup's real web interface (not a file being served up)
                # so do the Anonymous Web Acess check now
                self.check_anonymous_access()

                # possibly handle a form submit action (may change self.classname
                # and self.template, and may also append error/ok_messages)
                html = self.handle_action()

                if html:
                    self.write_html(html)
                    return

                # now render the page
                # we don't want clients caching our dynamic pages
                self.additional_headers['Cache-Control'] = 'no-cache'
                # Pragma: no-cache makes Mozilla and its ilk
                # double-load all pages!!
                #            self.additional_headers['Pragma'] = 'no-cache'

                # pages with messages added expire right now
                # simple views may be cached for a small amount of time
                # TODO? make page expire time configurable
                # <rj> always expire pages, as IE just doesn't seem to do the
                # right thing here :(
                date = time.time() - 1
                #if self.error_message or self.ok_message:
                #    date = time.time() - 1
                #else:
                #    date = time.time() + 5
                self.additional_headers['Expires'] = rfc822.formatdate(date)

                # render the content
                self.write_html(self.renderContext())
            except SendFile, designator:
                # The call to serve_file may result in an Unauthorised
                # exception or a NotModified exception.  Those
                # exceptions will be handled by the outermost set of
                # exception handlers.
                self.serve_file(designator)
            except SendStaticFile, file:
                self.serve_static_file(str(file))
            except IOError:
                # IOErrors here are due to the client disconnecting before
                # receiving the reply.
                pass
            except SysCallError:
                # OpenSSL.SSL.SysCallError is similar to IOError above
                pass

        except SeriousError, message:
            self.write_html(str(message))
        except Redirect, url:
            # let's redirect - if the url isn't None, then we need to do
            # the headers, otherwise the headers have been set before the
            # exception was raised
            if url:
                self.additional_headers['Location'] = str(url)
                self.response_code = 302
            self.write_html('Redirecting to <a href="%s">%s</a>'%(url, url))
        except LoginError, message:
            # The user tried to log in, but did not provide a valid
            # username and password.  If we support HTTP
            # authorization, send back a response that will cause the
            # browser to prompt the user again.
            if self.instance.config.WEB_HTTP_AUTH:
                self.response_code = http_.client.UNAUTHORIZED
                realm = self.instance.config.TRACKER_NAME
                self.setHeader("WWW-Authenticate",
                               "Basic realm=\"%s\"" % realm)
            else:
                self.response_code = http_.client.FORBIDDEN
            self.renderFrontPage(message)
        except Unauthorised, message:
            # users may always see the front page
            self.response_code = 403
            self.renderFrontPage(message)
        except NotModified:
            # send the 304 response
            self.response_code = 304
            self.header()
        except NotFound, e:
            self.response_code = 404
            self.template = '404'
            try:
                cl = self.db.getclass(self.classname)
                self.write_html(self.renderContext())
            except KeyError:
                # we can't map the URL to a class we know about
                # reraise the NotFound and let roundup_server
                # handle it
                raise NotFound(e)
        except FormError, e:
            self.error_message.append(self._('Form Error: ') + str(e))
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
        except:
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
                self.write_html(self._(error_message))
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
        hour = 60*60
        now = time.time()

        # XXX: hack - use OTK table to store last_clean time information
        #      'last_clean' string is used instead of otk key
        last_clean = self.db.getOTKManager().get('last_clean', 'last_use', 0)
        if now - last_clean < hour:
            return

        self.session_api.clean_up()
        self.db.getOTKManager().clean()
        self.db.getOTKManager().set('last_clean', last_use=now)
        self.db.commit(fail_ok=True)

    def determine_charset(self):
        """Look for client charset in the form parameters or browser cookie.

        If no charset requested by client, use storage charset (utf-8).

        If the charset is found, and differs from the storage charset,
        recode all form fields of type 'text/plain'
        """
        # look for client charset
        charset_parameter = 0
        if '@charset' in self.form:
            charset = self.form['@charset'].value
            if charset.lower() == "none":
                charset = ""
            charset_parameter = 1
        elif 'roundup_charset' in self.cookie:
            charset = self.cookie['roundup_charset'].value
        else:
            charset = None
        if charset:
            # make sure the charset is recognized
            try:
                codecs.lookup(charset)
            except LookupError:
                self.error_message.append(self._('Unrecognized charset: %r')
                    % charset)
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
                if num[0].lower() == 'x':
                    uc = int(num[1:], 16)
                else:
                    uc = int(num)
                return unichr(uc)

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
        if "@language" in self.form:
            language = self.form["@language"].value
            if language.lower() == "none":
                language = ""
            self.add_cookie("roundup_language", language)
        elif "roundup_language" in self.cookie:
            language = self.cookie["roundup_language"].value
        elif self.instance.config["WEB_USE_BROWSER_LANGUAGE"]:
            hal = self.env.get('HTTP_ACCEPT_LANGUAGE')
            language = accept_language.parse(hal)
        else:
            language = ""

        self.language = language
        if language:
            self.setTranslator(TranslationService.get_translation(
                    language,
                    tracker_home=self.instance.config["TRACKER_HOME"]))

    def determine_user(self):
        """Determine who the user is"""
        self.opendb('admin')

        # get session data from db
        # XXX: rename
        self.session_api = Session(self)

        # take the opportunity to cleanup expired sessions and otks
        self.clean_up()

        user = None
        # first up, try http authorization if enabled
        if self.instance.config['WEB_HTTP_AUTH']:
            if 'REMOTE_USER' in self.env:
                # we have external auth (e.g. by Apache)
                user = self.env['REMOTE_USER']
            elif self.env.get('HTTP_AUTHORIZATION', ''):
                # try handling Basic Auth ourselves
                auth = self.env['HTTP_AUTHORIZATION']
                scheme, challenge = auth.split(' ', 1)
                if scheme.lower() == 'basic':
                    try:
                        decoded = base64.decodestring(challenge)
                    except TypeError:
                        # invalid challenge
                        pass
                    username, password = decoded.split(':', 1)
                    try:
                        # Current user may not be None, otherwise
                        # instatiation of the login action will fail.
                        # So we set the user to anonymous first.
                        self.make_user_anonymous()
                        login = self.get_action_class('login')(self)
                        login.verifyLogin(username, password)
                    except LoginError, err:
                        self.make_user_anonymous()
                        raise
                    user = username

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

    def check_anonymous_access(self):
        """Check that the Anonymous user is actually allowed to use the web
        interface and short-circuit all further processing if they're not.
        """
        # allow Anonymous to use the "login" and "register" actions (noting
        # that "register" has its own "Register" permission check)

        if ':action' in self.form:
            action = self.form[':action']
        elif '@action' in self.form:
            action = self.form['@action']
        else:
            action = ''
        if isinstance(action, list):
            raise SeriousError('broken form: multiple @action values submitted')
        elif action != '':
            action = action.value.lower()
        if action in ('login', 'register'):
            return

        # allow Anonymous to view the "user" "register" template if they're
        # allowed to register
        if (self.db.security.hasPermission('Register', self.userid, 'user')
                and self.classname == 'user' and self.template == 'register'):
            return

        # otherwise for everything else
        if self.user == 'anonymous':
            if not self.db.security.hasPermission('Web Access', self.userid):
                raise Unauthorised(self._("Anonymous users are not "
                    "allowed to use the web interface"))

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
        else:
            if self.instance.optimize:
                self.db.setCurrentUser(username)
            else:
                self.db.close()
                self.db = self.instance.open(username)
                # The old session API refers to the closed database;
                # we can no longer use it.
                self.session_api = Session(self)


    def determine_context(self, dre=re.compile(r'([^\d]+)0*(\d+)')):
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
        for key in self.form:
            if self.FV_TEMPLATE.match(key):
                template_override = self.form[key].value
            elif self.FV_OK_MESSAGE.match(key):
                ok_message = self.form[key].value
                ok_message = clean_message(ok_message)
            elif self.FV_ERROR_MESSAGE.match(key):
                error_message = self.form[key].value
                error_message = clean_message(error_message)

        # see if we were passed in a message
        if ok_message:
            self.ok_message.append(ok_message)
        if error_message:
            self.error_message.append(error_message)

        # determine the classname and possibly nodeid
        path = self.path.split('/')
        if not path or path[0] in ('', 'home', 'index'):
            if template_override is not None:
                self.template = template_override
            else:
                self.template = ''
            return
        elif path[0] in ('_file', '@@file'):
            raise SendStaticFile(os.path.join(*path[1:]))
        else:
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
                raise NotFound('%s/%s'%(self.classname, self.nodeid))
            if not klass.hasnode(self.nodeid):
                raise NotFound('%s/%s'%(self.classname, self.nodeid))
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

    def serve_file(self, designator, dre=re.compile(r'([^\d]+)(\d+)')):
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

        try:
            mime_type = klass.get(nodeid, 'type')
        except IndexError, e:
            raise NotFound(e)
        # Can happen for msg class:
        if not mime_type:
            mime_type = 'text/plain'

        # if the mime_type is HTML-ish then make sure we're allowed to serve up
        # HTML-ish content
        if mime_type in ('text/html', 'text/x-html'):
            if not self.instance.config['WEB_ALLOW_HTML_FILE']:
                # do NOT serve the content up as HTML
                mime_type = 'application/octet-stream'

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

        self._serve_file(lmt, mime_type, content, filename)

    def serve_static_file(self, file):
        """ Serve up the file named from the templates dir
        """
        # figure the filename - try STATIC_FILES, then TEMPLATES dir
        for dir_option in ('STATIC_FILES', 'TEMPLATES'):
            prefix = self.instance.config[dir_option]
            if not prefix:
                continue
            # ensure the load doesn't try to poke outside
            # of the static files directory
            prefix = os.path.normpath(prefix)
            filename = os.path.normpath(os.path.join(prefix, file))
            if os.path.isfile(filename) and filename.startswith(prefix):
                break
        else:
            raise NotFound(file)

        # last-modified time
        lmt = os.stat(filename)[stat.ST_MTIME]

        # detemine meta-type
        file = str(file)
        mime_type = mimetypes.guess_type(file)[0]
        if not mime_type:
            if file.endswith('.css'):
                mime_type = 'text/css'
            else:
                mime_type = 'text/plain'

        self._serve_file(lmt, mime_type, '', filename)

    def _serve_file(self, lmt, mime_type, content=None, filename=None):
        """ guts of serve_file() and serve_static_file()
        """

        # spit out headers
        self.additional_headers['Content-Type'] = mime_type
        self.additional_headers['Last-Modified'] = rfc822.formatdate(lmt)

        ims = None
        # see if there's an if-modified-since...
        # XXX see which interfaces set this
        #if hasattr(self.request, 'headers'):
            #ims = self.request.headers.getheader('if-modified-since')
        if 'HTTP_IF_MODIFIED_SINCE' in self.env:
            # cgi will put the header in the env var
            ims = self.env['HTTP_IF_MODIFIED_SINCE']
        if ims:
            ims = rfc822.parsedate(ims)[:6]
            lmtt = time.gmtime(lmt)[:6]
            if lmtt <= ims:
                raise NotModified

        if filename:
            self.write_file(filename)
        else:
            self.additional_headers['Content-Length'] = str(len(content))
            self.write(content)

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
        part = MIMEBase('text', 'html')
        part.set_charset('utf-8')
        part.set_payload(html)
        encode_quopri(part)
        message.attach(part)
        part = MIMEText(txt)
        message.attach(part)
        self.mailer.smtp_send(to, message.as_string())

    def renderFrontPage(self, message):
        """Return the front page of the tracker."""

        self.classname = self.nodeid = None
        self.template = ''
        self.error_message.append(message)
        self.write_html(self.renderContext())

    def renderContext(self):
        """ Return a PageTemplate for the named page
        """
        name = self.classname
        view = self.template

        # catch errors so we can handle PT rendering errors more nicely
        args = {
            'ok_message': self.ok_message,
            'error_message': self.error_message
        }
        try:
            pt = self.instance.templates.load(name, view)
            # let the template render figure stuff out
            result = pt.render(self, None, None, **args)
            self.additional_headers['Content-Type'] = pt.content_type
            if self.env.get('CGI_SHOW_TIMING', ''):
                if self.env['CGI_SHOW_TIMING'].upper() == 'COMMENT':
                    timings = {'starttag': '<!-- ', 'endtag': ' -->'}
                else:
                    timings = {'starttag': '<p>', 'endtag': '</p>'}
                timings['seconds'] = time.time()-self.start
                s = self._('%(starttag)sTime elapsed: %(seconds)fs%(endtag)s\n'
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
        except templating.NoTemplate, message:
            return '<strong>%s</strong>'%cgi.escape(str(message))
        except templating.Unauthorised, message:
            raise Unauthorised(cgi.escape(str(message)))
        except:
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
                return self._(error_message)
            except:
                # Reraise the original exception.  The user will
                # receive an error message, and the adminstrator will
                # receive a traceback, albeit with less information
                # than the one we tried to generate above.
                raise exc_info[0], exc_info[1], exc_info[2]

    # these are the actions that are available
    actions = (
        ('edit',        EditItemAction),
        ('editcsv',     EditCSVAction),
        ('new',         NewItemAction),
        ('register',    RegisterAction),
        ('confrego',    ConfRegoAction),
        ('passrst',     PassResetAction),
        ('login',       LoginAction),
        ('logout',      LogoutAction),
        ('search',      SearchAction),
        ('retire',      RetireAction),
        ('show',        ShowAction),
        ('export_csv',  ExportCSVAction),
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
        if ':action' in self.form:
            action = self.form[':action']
        elif '@action' in self.form:
            action = self.form['@action']
        else:
            return None

        if isinstance(action, list):
            raise SeriousError('broken form: multiple @action values submitted')
        else:
            action = action.value.lower()

        try:
            action_klass = self.get_action_class(action)

            # call the mapped action
            if isinstance(action_klass, type('')):
                # old way of specifying actions
                return getattr(self, action_klass)()
            else:
                return action_klass(self).execute()

        except (ValueError, Reject), err:
            self.error_message.append(str(err))

    def get_action_class(self, action_name):
        if (hasattr(self.instance, 'cgi_actions') and
                action_name in self.instance.cgi_actions):
            # tracker-defined action
            action_klass = self.instance.cgi_actions[action_name]
        else:
            # go with a default
            for name, action_klass in self.actions:
                if name == action_name:
                    break
            else:
                raise ValueError('No such action "%s"'%cgi.escape(action_name))
        return action_klass

    def _socket_op(self, call, *args, **kwargs):
        """Execute socket-related operation, catch common network errors

        Parameters:
            call: a callable to execute
            args, kwargs: call arguments

        """
        try:
            call(*args, **kwargs)
        except socket.error, err:
            err_errno = getattr (err, 'errno', None)
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

    def write(self, content):
        if not self.headers_done:
            self.header()
        if self.env['REQUEST_METHOD'] != 'HEAD':
            self._socket_op(self.request.wfile.write, content)

    def write_html(self, content):
        if not self.headers_done:
            # at this point, we are sure about Content-Type
            if 'Content-Type' not in self.additional_headers:
                self.additional_headers['Content-Type'] = \
                    'text/html; charset=%s' % self.charset
            self.header()

        if self.env['REQUEST_METHOD'] == 'HEAD':
            # client doesn't care about content
            return

        if self.charset != self.STORAGE_CHARSET:
            # recode output
            content = content.decode(self.STORAGE_CHARSET, 'replace')
            content = content.encode(self.charset, 'xmlcharrefreplace')

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
                return
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
        if not first:
            return None
       # Convert the first and last positions to integers.
        try:
            first = int(first)
            if last:
                last = int(last)
            else:
                last = length - 1
        except:
            # The positions could not be parsed as integers.
            return None
        # Check that the range makes sense.
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
        """Send the contents of 'filename' to the user."""

        # Determine the length of the file.
        stat_info = os.stat(filename)
        length = stat_info[stat.ST_SIZE]
        # Assume we will return the entire file.
        offset = 0
        # If the headers have not already been finalized,
        if not self.headers_done:
            # RFC 2616 14.19: ETag
            #
            # Compute the entity tag, in a format similar to that
            # used by Apache.
            etag = '"%x-%x-%x"' % (stat_info[stat.ST_INO],
                                   length,
                                   stat_info[stat.ST_MTIME])
            self.setHeader("ETag", etag)
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
            # Send the HTTP header.
            self.header()
        # If the client doesn't actually want the body, or if we are
        # indicating an invalid range.
        if (self.env['REQUEST_METHOD'] == 'HEAD'
            or self.response_code == http_.client.REQUESTED_RANGE_NOT_SATISFIABLE):
            return
        # Use the optimized "sendfile" operation, if possible.
        if hasattr(self.request, "sendfile"):
            self._socket_op(self.request.sendfile, filename, offset, length)
            return
        # Fallback to the "write" operation.
        f = open(filename, 'rb')
        try:
            if offset:
                f.seek(offset)
            content = f.read(length)
        finally:
            f.close()
        self.write(content)

    def setHeader(self, header, value):
        """Override a header to be returned to the user's browser.
        """
        self.additional_headers[header] = value

    def header(self, headers=None, response=None):
        """Put up the appropriate header.
        """
        if headers is None:
            headers = {'Content-Type':'text/html; charset=utf-8'}
        if response is None:
            response = self.response_code

        # update with additional info
        headers.update(self.additional_headers)

        if headers.get('Content-Type', 'text/html') == 'text/html':
            headers['Content-Type'] = 'text/html; charset=utf-8'

        headers = list(headers.items())

        for ((path, name), (value, expire)) in self._cookies.iteritems():
            cookie = "%s=%s; Path=%s;"%(name, value, path)
            if expire is not None:
                cookie += " expires=%s;"%get_cookie_date(expire)
            # mark as secure if https, see issue2550689
            if self.secure:
                cookie += " secure;"
            # prevent theft of session cookie, see issue2550689
            cookie += " HttpOnly;"
            headers.append(('Set-Cookie', cookie))

        self._socket_op(self.request.start_response, headers, response)

        self.headers_done = 1
        if self.debug:
            self.headers_sent = headers

    def add_cookie(self, name, value, expire=86400*365, path=None):
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
        except MessageSendError, e:
            self.error_message.append(str(e))
            return 0
        return 1

    def parsePropsFromForm(self, create=0):
        return FormParser(self).parse(create=create)

# vim: set et sts=4 sw=4 :
