# $Id: client.py,v 1.239 2008-08-18 05:04:02 richard Exp $

"""WWW request handler (also used in the stand-alone server).
"""
__docformat__ = 'restructuredtext'

import base64, binascii, cgi, codecs, mimetypes, os
import random, re, rfc822, stat, time, urllib, urlparse
import Cookie, socket, errno
from Cookie import CookieError, BaseCookie, SimpleCookie

from roundup import roundupdb, date, hyperdb, password
from roundup.cgi import templating, cgitb, TranslationService
from roundup.cgi.actions import *
from roundup.exceptions import *
from roundup.cgi.exceptions import *
from roundup.cgi.form_parser import FormParser
from roundup.mailer import Mailer, MessageSendError
from roundup.cgi import accept_language

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

# used to clean messages passed through CGI variables - HTML-escape any tag
# that isn't <a href="">, <i>, <b> and <br> (including XHTML variants) so
# that people can't pass through nasties like <script>, <iframe>, ...
CLEAN_MESSAGE_RE = r'(<(/?(.*?)(\s*href="[^"]")?\s*/?)>)'
def clean_message(message, mc=re.compile(CLEAN_MESSAGE_RE, re.I)):
    return mc.sub(clean_message_callback, message)
def clean_message_callback(match, ok={'a':1,'i':1,'b':1,'br':1}):
    ''' Strip all non <a>,<i>,<b> and <br> tags from a string
    '''
    if ok.has_key(match.group(3).lower()):
        return match.group(1)
    return '&lt;%s&gt;'%match.group(2)


error_message = ""'''<html><head><title>An error has occurred</title></head>
<body><h1>An error has occurred</h1>
<p>A problem was encountered processing your request.
The tracker maintainers have been notified of the problem.</p>
</body></html>'''


class LiberalCookie(SimpleCookie):
    ''' Python's SimpleCookie throws an exception if the cookie uses invalid
        syntax.  Other applications on the same server may have done precisely
        this, preventing roundup from working through no fault of roundup.
        Numerous other python apps have run into the same problem:

        trac: http://trac.edgewall.org/ticket/2256
        mailman: http://bugs.python.org/issue472646

        This particular implementation comes from trac's solution to the
        problem. Unfortunately it requires some hackery in SimpleCookie's
        internals to provide a more liberal __set method.
    '''
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
    '''
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

    '''

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
        ''' generate a unique session key '''
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
        '''Remove expired sessions'''
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
        ''' update timestamp in db to avoid expiration

            if 'set_cookie' is True, set cookie with 'expire' seconds lifetime
            if 'expire' is None - session will be closed with the browser
             
            XXX the session can be purged within a week even if a cookie
                lifetime is longer
        '''
        self.session_db.updateTimestamp(self._sid)
        self.client.db.commit()

        if set_cookie:
            self.client.add_cookie(self.cookie_name, self._sid, expire=expire)



class Client:
    '''Instantiate to handle one CGI request.

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
    '''

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

        # check the tracker_we setting
        if not self.base.endswith('/'):
            self.base = self.base + '/'

        # this is the "cookie path" for this tracker (ie. the path part of
        # the "base" url)
        self.cookie_path = urlparse.urlparse(self.base)[2]
        # cookies to set in http responce
        # {(path, name): (value, expire)}
        self._cookies = {}

        # see if we need to re-parse the environment for the form (eg Zope)
        if form is None:
            self.form = cgi.FieldStorage(environ=env)
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
        ''' Wrap the real main in a try/finally so we always close off the db.
        '''
        try:
            self.inner_main()
        finally:
            if hasattr(self, 'db'):
                self.db.close()

    def inner_main(self):
        '''Process a request.

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
        '''
        self.ok_message = []
        self.error_message = []
        try:
            self.determine_charset()
            self.determine_language()

            # make sure we're identified (even anonymously)
            self.determine_user()

            # figure out the context and desired content template
            self.determine_context()

            # possibly handle a form submit action (may change self.classname
            # and self.template, and may also append error/ok_messages)
            html = self.handle_action()

            if html:
                self.write_html(html)
                return

            # now render the page
            # we don't want clients caching our dynamic pages
            self.additional_headers['Cache-Control'] = 'no-cache'
# Pragma: no-cache makes Mozilla and its ilk double-load all pages!!
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
            try:
                self.write_html(self.renderContext())
            except IOError:
                # IOErrors here are due to the client disconnecting before
                # recieving the reply.
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
        except SendFile, designator:
            try:
                self.serve_file(designator)
            except NotModified:
                # send the 304 response
                self.response_code = 304
                self.header()
        except SendStaticFile, file:
            try:
                self.serve_static_file(str(file))
            except NotModified:
                # send the 304 response
                self.response_code = 304
                self.header()
        except Unauthorised, message:
            # users may always see the front page
            self.classname = self.nodeid = None
            self.template = ''
            self.error_message.append(message)
            self.write_html(self.renderContext())
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
                raise NotFound, e
        except FormError, e:
            self.error_message.append(self._('Form Error: ') + str(e))
            self.write_html(self.renderContext())
        except:
            if self.instance.config.WEB_DEBUG:
                self.write_html(cgitb.html(i18n=self.translator))
            else:
                self.mailer.exception_message()
                return self.write_html(self._(error_message))

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
        if self.form.has_key('@charset'):
            charset = self.form['@charset'].value
            if charset.lower() == "none":
                charset = ""
            charset_parameter = 1
        elif self.cookie.has_key('roundup_charset'):
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

            for field_name in self.form.keys():
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
        if self.form.has_key("@language"):
            language = self.form["@language"].value
            if language.lower() == "none":
                language = ""
            self.add_cookie("roundup_language", language)
        elif self.cookie.has_key("roundup_language"):
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
            if self.env.has_key('REMOTE_USER'):
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
                    username, password = decoded.split(':')
                    try:
                        login = self.get_action_class('login')(self)
                        login.verifyLogin(username, password)
                    except LoginError, err:
                        self.make_user_anonymous()
                        self.response_code = 403
                        raise Unauthorised, err

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
            if not self.db.security.hasPermission('Web Access', self.userid):
                raise Unauthorised, self._("Anonymous users are not "
                    "allowed to use the web interface")
        else:
            self.user = user

        # reopen the database as the correct user
        self.opendb(self.user)

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
        for key in self.form.keys():
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
            raise SendStaticFile, os.path.join(*path[1:])
        else:
            self.classname = path[0]
            if len(path) > 1:
                # send the file identified by the designator in path[0]
                raise SendFile, path[0]

        # see if we got a designator
        m = dre.match(self.classname)
        if m:
            self.classname = m.group(1)
            self.nodeid = m.group(2)
            try:
                klass = self.db.getclass(self.classname)
            except KeyError:
                raise NotFound, '%s/%s'%(self.classname, self.nodeid)
            if not klass.hasnode(self.nodeid):
                raise NotFound, '%s/%s'%(self.classname, self.nodeid)
            # with a designator, we default to item view
            self.template = 'item'
        else:
            # with only a class, we default to index view
            self.template = 'index'

        # make sure the classname is valid
        try:
            self.db.getclass(self.classname)
        except KeyError:
            raise NotFound, self.classname

        # see if we have a template override
        if template_override is not None:
            self.template = template_override

    def serve_file(self, designator, dre=re.compile(r'([^\d]+)(\d+)')):
        ''' Serve the file from the content property of the designated item.
        '''
        m = dre.match(str(designator))
        if not m:
            raise NotFound, str(designator)
        classname, nodeid = m.group(1), m.group(2)

        klass = self.db.getclass(classname)

        # make sure we have the appropriate properties
        props = klass.getprops()
        if not props.has_key('type'):
            raise NotFound, designator
        if not props.has_key('content'):
            raise NotFound, designator

        # make sure we have permission
        if not self.db.security.hasPermission('View', self.userid,
                classname, 'content', nodeid):
            raise Unauthorised, self._("You are not allowed to view "
                "this file.")

        mime_type = klass.get(nodeid, 'type')
        content = klass.get(nodeid, 'content')
        lmt = klass.get(nodeid, 'activity').timestamp()

        self._serve_file(lmt, mime_type, content)

    def serve_static_file(self, file):
        ''' Serve up the file named from the templates dir
        '''
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
            raise NotFound, file

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

        # snarf the content
        f = open(filename, 'rb')
        try:
            content = f.read()
        finally:
            f.close()

        self._serve_file(lmt, mime_type, content)

    def _serve_file(self, lmt, mime_type, content):
        ''' guts of serve_file() and serve_static_file()
        '''
        # spit out headers
        self.additional_headers['Content-Type'] = mime_type
        self.additional_headers['Content-Length'] = str(len(content))
        self.additional_headers['Last-Modified'] = rfc822.formatdate(lmt)

        ims = None
        # see if there's an if-modified-since...
        # XXX see which interfaces set this
        #if hasattr(self.request, 'headers'):
            #ims = self.request.headers.getheader('if-modified-since')
        if self.env.has_key('HTTP_IF_MODIFIED_SINCE'):
            # cgi will put the header in the env var
            ims = self.env['HTTP_IF_MODIFIED_SINCE']
        if ims:
            ims = rfc822.parsedate(ims)[:6]
            lmtt = time.gmtime(lmt)[:6]
            if lmtt <= ims:
                raise NotModified

        self.write(content)

    def renderContext(self):
        ''' Return a PageTemplate for the named page
        '''
        name = self.classname
        extension = self.template
        pt = self.instance.templates.get(name, extension)

        # catch errors so we can handle PT rendering errors more nicely
        args = {
            'ok_message': self.ok_message,
            'error_message': self.error_message
        }
        try:
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
            return '<strong>%s</strong>'%message
        except templating.Unauthorised, message:
            raise Unauthorised, str(message)
        except:
            # everything else
            return cgitb.pt_html(i18n=self.translator)

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
        ''' Determine whether there should be an Action called.

            The action is defined by the form variable :action which
            identifies the method on this object to call. The actions
            are defined in the "actions" sequence on this class.

            Actions may return a page (by default HTML) to return to the
            user, bypassing the usual template rendering.

            We explicitly catch Reject and ValueError exceptions and
            present their messages to the user.
        '''
        if self.form.has_key(':action'):
            action = self.form[':action'].value.lower()
        elif self.form.has_key('@action'):
            action = self.form['@action'].value.lower()
        else:
            return None

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
                self.instance.cgi_actions.has_key(action_name)):
            # tracker-defined action
            action_klass = self.instance.cgi_actions[action_name]
        else:
            # go with a default
            for name, action_klass in self.actions:
                if name == action_name:
                    break
            else:
                raise ValueError, 'No such action "%s"'%action_name
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

    def write(self, content):
        if not self.headers_done:
            self.header()
        if self.env['REQUEST_METHOD'] != 'HEAD':
            self._socket_op(self.request.wfile.write, content)

    def write_html(self, content):
        if not self.headers_done:
            # at this point, we are sure about Content-Type
            if not self.additional_headers.has_key('Content-Type'):
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

    def setHeader(self, header, value):
        '''Override a header to be returned to the user's browser.
        '''
        self.additional_headers[header] = value

    def header(self, headers=None, response=None):
        '''Put up the appropriate header.
        '''
        if headers is None:
            headers = {'Content-Type':'text/html; charset=utf-8'}
        if response is None:
            response = self.response_code

        # update with additional info
        headers.update(self.additional_headers)

        if headers.get('Content-Type', 'text/html') == 'text/html':
            headers['Content-Type'] = 'text/html; charset=utf-8'

        headers = headers.items()

        for ((path, name), (value, expire)) in self._cookies.items():
            cookie = "%s=%s; Path=%s;"%(name, value, path)
            if expire is not None:
                cookie += " expires=%s;"%Cookie._getdate(expire)
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

    def set_cookie(self, user, expire=None):
        """Deprecated. Use session_api calls directly

        XXX remove
        """

        # insert the session in the session db
        self.session_api.set(user=user)
        # refresh session cookie
        self.session_api.update(set_cookie=True, expire=expire)

    def make_user_anonymous(self):
        ''' Make us anonymous

            This method used to handle non-existence of the 'anonymous'
            user, but that user is mandatory now.
        '''
        self.userid = self.db.user.lookup('anonymous')
        self.user = 'anonymous'

    def standard_message(self, to, subject, body, author=None):
        '''Send a standard email message from Roundup.

        "to"      - recipients list
        "subject" - Subject
        "body"    - Message
        "author"  - (name, address) tuple or None for admin email

        Arguments are passed to the Mailer.standard_message code.
        '''
        try:
            self.mailer.standard_message(to, subject, body, author)
        except MessageSendError, e:
            self.error_message.append(str(e))
            return 0
        return 1

    def parsePropsFromForm(self, create=0):
        return FormParser(self).parse(create=create)

# vim: set et sts=4 sw=4 :
