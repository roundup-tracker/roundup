# $Id: client.py,v 1.159 2004-02-14 11:27:23 jlgijsbers Exp $

"""WWW request handler (also used in the stand-alone server).
"""
__docformat__ = 'restructuredtext'

import os, os.path, cgi, StringIO, urlparse, re, traceback, mimetypes, urllib
import binascii, Cookie, time, random, stat, rfc822

from roundup import roundupdb, date, hyperdb, password
from roundup.i18n import _
from roundup.cgi import templating, cgitb
from roundup.cgi.actions import *
from roundup.cgi.exceptions import *
from roundup.cgi.form_parser import FormParser
from roundup.mailer import Mailer, MessageSendError

def initialiseSecurity(security):
    '''Create some Permissions and Roles on the security object

    This function is directly invoked by security.Security.__init__()
    as a part of the Security object instantiation.
    '''
    security.addPermission(name="Web Registration",
        description="User may register through the web")
    p = security.addPermission(name="Web Access",
        description="User may access the web interface")
    security.addPermissionToRole('Admin', p)

    # doing Role stuff through the web - make sure Admin can
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

    During the processing of a request, the following attributes are used:

    - "error_message" holds a list of error messages
    - "ok_message" holds a list of OK messages
    - "session" is the current user session id
    - "user" is the current user's name
    - "userid" is the current user's id
    - "template" is the current :template context
    - "classname" is the current class context name
    - "nodeid" is the current context item id

    User Identification:
     If the user has no login cookie, then they are anonymous and are logged
     in as that user. This typically gives them all Permissions assigned to the
     Anonymous Role.

     Once a user logs in, they are assigned a session. The Client instance
     keeps the nodeid of the session as the "session" attribute.

    Special form variables:
     Note that in various places throughout this code, special form
     variables of the form :<name> are used. The colon (":") part may
     actually be one of either ":" or "@".
    '''

    #
    # special form variables
    #
    FV_TEMPLATE = re.compile(r'[@:]template')
    FV_OK_MESSAGE = re.compile(r'[@:]ok_message')
    FV_ERROR_MESSAGE = re.compile(r'[@:]error_message')

    # Note: index page stuff doesn't appear here:
    # columns, sort, sortdir, filter, group, groupdir, search_text,
    # pagesize, startwith

    def __init__(self, instance, request, env, form=None):
        hyperdb.traceMark()
        self.instance = instance
        self.request = request
        self.env = env
        self.mailer = Mailer(instance.config)

        # save off the path
        self.path = env['PATH_INFO']

        # this is the base URL for this tracker
        self.base = self.instance.config.TRACKER_WEB

        # this is the "cookie path" for this tracker (ie. the path part of
        # the "base" url)
        self.cookie_path = urlparse.urlparse(self.base)[2]
        self.cookie_name = 'roundup_session_' + re.sub('[^a-zA-Z]', '',
            self.instance.config.TRACKER_NAME)

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

        1. figure out who we are, defaulting to the "anonymous" user
           see determine_user
        2. figure out what the request is for - the context
           see determine_context
        3. handle any requested action (item edit, search, ...)
           see handle_action
        4. render a template, resulting in HTML output

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
            # figure out the context and desired content template
            # do this first so we don't authenticate for static files
            # Note: this method opens the database as "admin" in order to
            # perform context checks
            self.determine_context()

            # make sure we're identified (even anonymously)
            self.determine_user()

            # possibly handle a form submit action (may change self.classname
            # and self.template, and may also append error/ok_messages)
            self.handle_action()

            # now render the page
            # we don't want clients caching our dynamic pages
            self.additional_headers['Cache-Control'] = 'no-cache'
# Pragma: no-cache makes Mozilla and its ilk double-load all pages!!
#            self.additional_headers['Pragma'] = 'no-cache'

            # expire this page 5 seconds from now
            date = rfc822.formatdate(time.time() + 5)
            self.additional_headers['Expires'] = date

            # render the content
            self.write(self.renderContext())
        except Redirect, url:
            # let's redirect - if the url isn't None, then we need to do
            # the headers, otherwise the headers have been set before the
            # exception was raised
            if url:
                self.additional_headers['Location'] = url
                self.response_code = 302
            self.write('Redirecting to <a href="%s">%s</a>'%(url, url))
        except SendFile, designator:
            self.serve_file(designator)
        except SendStaticFile, file:
            try:
                self.serve_static_file(str(file))
            except NotModified:
                # send the 304 response
                self.request.send_response(304)
                self.request.end_headers()
        except Unauthorised, message:
            # users may always see the front page
            self.classname = self.nodeid = None
            self.template = ''
            self.error_message.append(message)
            self.write(self.renderContext())
        except NotFound:
            # pass through
            raise
        except FormError, e:
            self.error_message.append(_('Form Error: ') + str(e))
            self.write(self.renderContext())
        except:
            # everything else
            self.write(cgitb.html())

    def clean_sessions(self):
        """Age sessions, remove when they haven't been used for a week.
        
        Do it only once an hour.

        Note: also cleans One Time Keys, and other "session" based stuff.
        """
        sessions = self.db.sessions
        last_clean = sessions.get('last_clean', 'last_use') or 0

        week = 60*60*24*7
        hour = 60*60
        now = time.time()
        if now - last_clean > hour:
            # remove aged sessions
            for sessid in sessions.list():
                interval = now - sessions.get(sessid, 'last_use')
                if interval > week:
                    sessions.destroy(sessid)
            # remove aged otks
            otks = self.db.otks
            for sessid in otks.list():
                interval = now - otks.get(sessid, '__time')
                if interval > week:
                    otks.destroy(sessid)
            sessions.set('last_clean', last_use=time.time())

    def determine_user(self):
        ''' Determine who the user is
        '''
        # determine the uid to use
        self.opendb('admin')

        # make sure we have the session Class
        self.clean_sessions()
        sessions = self.db.sessions

        # first up, try the REMOTE_USER var (from HTTP Basic Auth handled
        # by a front-end HTTP server)
        try:
            user = os.getenv('REMOTE_USER')
        except KeyError:
            pass

        # look up the user session cookie (may override the REMOTE_USER)
        cookie = Cookie.Cookie(self.env.get('HTTP_COOKIE', ''))
        user = 'anonymous'
        if (cookie.has_key(self.cookie_name) and
                cookie[self.cookie_name].value != 'deleted'):

            # get the session key from the cookie
            self.session = cookie[self.cookie_name].value
            # get the user from the session
            try:
                # update the lifetime datestamp
                sessions.set(self.session, last_use=time.time())
                sessions.commit()
                user = sessions.get(self.session, 'user')
            except KeyError:
                # not valid, ignore id
                pass

        # sanity check on the user still being valid, getting the userid
        # at the same time
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

    def determine_context(self, dre=re.compile(r'([^\d]+)(\d+)')):
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

        # we need the db for further context stuff - open it as admin
        self.opendb('admin')

        # see if we got a designator
        m = dre.match(self.classname)
        if m:
            self.classname = m.group(1)
            self.nodeid = m.group(2)
            if not self.db.getclass(self.classname).hasnode(self.nodeid):
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

        self.opendb('admin')
        klass = self.db.getclass(classname)

        # make sure we have the appropriate properties
        props = klass.getprops()
        if not props.has_key('type'):
            raise NotFound, designator
        if not props.has_key('content'):
            raise NotFound, designator

        mime_type = klass.get(nodeid, 'type')
        content = klass.get(nodeid, 'content')
        lmt = klass.get(nodeid, 'activity').timestamp()

        self._serve_file(lmt, mime_type, content)

    def serve_static_file(self, file):
        ''' Serve up the file named from the templates dir
        '''
        filename = os.path.join(self.instance.config.TEMPLATES, file)

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

    def _serve_file(self, last_modified, mime_type, content):
        ''' guts of serve_file() and serve_static_file()
        '''
        ims = None
        # see if there's an if-modified-since...
        if hasattr(self.request, 'headers'):
            ims = self.request.headers.getheader('if-modified-since')
        elif self.env.has_key('HTTP_IF_MODIFIED_SINCE'):
            # cgi will put the header in the env var
            ims = self.env['HTTP_IF_MODIFIED_SINCE']
        if ims:
            ims = rfc822.parsedate(ims)[:6]
            lmtt = time.gmtime(lmt)[:6]
            if lmtt <= ims:
                raise NotModified

        # spit out headers
        self.additional_headers['Content-Type'] = mime_type
        self.additional_headers['Content-Length'] = len(content)
        lmt = rfc822.formatdate(last_modified)
        self.additional_headers['Last-Modifed'] = lmt
        self.write(content)

    def renderContext(self):
        ''' Return a PageTemplate for the named page
        '''
        name = self.classname
        extension = self.template
        pt = templating.Templates(self.instance.config.TEMPLATES).get(name,
            extension)

        # catch errors so we can handle PT rendering errors more nicely
        args = {
            'ok_message': self.ok_message,
            'error_message': self.error_message
        }
        try:
            # let the template render figure stuff out
            result = pt.render(self, None, None, **args)
            self.additional_headers['Content-Type'] = pt.content_type
            return result
        except templating.NoTemplate, message:
            return '<strong>%s</strong>'%message
        except templating.Unauthorised, message:
            raise Unauthorised, str(message)
        except:
            # everything else
            return cgitb.pt_html()

    # these are the actions that are available
    actions = (
        ('edit',     EditItemAction),
        ('editcsv',  EditCSVAction),
        ('new',      NewItemAction),
        ('register', RegisterAction),
        ('confrego', ConfRegoAction),
        ('passrst',  PassResetAction),
        ('login',    LoginAction),
        ('logout',   LogoutAction),
        ('search',   SearchAction),
        ('retire',   RetireAction),
        ('show',     ShowAction),
    )
    def handle_action(self):
        ''' Determine whether there should be an Action called.

            The action is defined by the form variable :action which
            identifies the method on this object to call. The actions
            are defined in the "actions" sequence on this class.
        '''
        if self.form.has_key(':action'):
            action = self.form[':action'].value.lower()
        elif self.form.has_key('@action'):
            action = self.form['@action'].value.lower()
        else:
            return None
        try:
            # get the action, validate it
            for name, action_klass in self.actions:
                if name == action:
                    break
            else:
                raise ValueError, 'No such action "%s"'%action
            # call the mapped action
            try:
                action_klass(self).handle()
            except TypeError:
                # Old way of specifying actions.
                getattr(self, action_klass)()
                
        except ValueError, err:
            self.error_message.append(str(err))

    def write(self, content):
        if not self.headers_done:
            self.header()
        self.request.wfile.write(content)

    def header(self, headers=None, response=None):
        '''Put up the appropriate header.
        '''
        if headers is None:
            headers = {'Content-Type':'text/html'}
        if response is None:
            response = self.response_code

        # update with additional info
        headers.update(self.additional_headers)

        if not headers.has_key('Content-Type'):
            headers['Content-Type'] = 'text/html'
        self.request.send_response(response)
        for entry in headers.items():
            self.request.send_header(*entry)
        self.request.end_headers()
        self.headers_done = 1
        if self.debug:
            self.headers_sent = headers

    def set_cookie(self, user):
        """Set up a session cookie for the user.

        Also store away the user's login info against the session.
        """
        # TODO generate a much, much stronger session key ;)
        self.session = binascii.b2a_base64(repr(random.random())).strip()

        # clean up the base64
        if self.session[-1] == '=':
            if self.session[-2] == '=':
                self.session = self.session[:-2]
            else:
                self.session = self.session[:-1]

        # insert the session in the sessiondb
        self.db.sessions.set(self.session, user=user, last_use=time.time())

        # and commit immediately
        self.db.sessions.commit()

        # expire us in a long, long time
        expire = Cookie._getdate(86400*365)

        # generate the cookie path - make sure it has a trailing '/'
        self.additional_headers['Set-Cookie'] = \
          '%s=%s; expires=%s; Path=%s;'%(self.cookie_name, self.session,
            expire, self.cookie_path)

    def make_user_anonymous(self):
        ''' Make us anonymous

            This method used to handle non-existence of the 'anonymous'
            user, but that user is mandatory now.
        '''
        self.userid = self.db.user.lookup('anonymous')
        self.user = 'anonymous'

    def opendb(self, user):
        ''' Open the database.
        '''
        # open the db if the user has changed
        if not hasattr(self, 'db') or user != self.db.journaltag:
            if hasattr(self, 'db'):
                self.db.close()
            self.db = self.instance.open(user)

    def standard_message(self, to, subject, body, author=None):
        try:
            self.mailer.standard_message(to, subject, body, author)
            return 1
        except MessageSendError, e:
            self.error_message.append(str(e))

    def parsePropsFromForm(self, create=False):
        return FormParser(self).parse(create=create)

