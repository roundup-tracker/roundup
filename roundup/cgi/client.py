# $Id: client.py,v 1.133 2003-09-06 07:27:30 jlgijsbers Exp $

__doc__ = """
WWW request handler (also used in the stand-alone server).
"""

import os, os.path, cgi, StringIO, urlparse, re, traceback, mimetypes, urllib
import binascii, Cookie, time, random, MimeWriter, smtplib, socket, quopri
import stat, rfc822, string

from roundup import roundupdb, date, hyperdb, password, token, rcsv
from roundup.i18n import _
from roundup.cgi.templating import Templates, HTMLRequest, NoTemplate
from roundup.cgi import cgitb
from roundup.cgi.PageTemplates import PageTemplate
from roundup.rfc2822 import encode_header
from roundup.mailgw import uidFromAddress, openSMTPConnection

class HTTPException(Exception):
      pass
class  Unauthorised(HTTPException):
       pass
class  NotFound(HTTPException):
       pass
class  Redirect(HTTPException):
       pass
class  NotModified(HTTPException):
       pass

# set to indicate to roundup not to actually _send_ email
# this var must contain a file to write the mail to
SENDMAILDEBUG = os.environ.get('SENDMAILDEBUG', '')

# used by a couple of routines
chars = string.letters+string.digits

# XXX actually _use_ FormError
class FormError(ValueError):
    ''' An "expected" exception occurred during form parsing.
        - ie. something we know can go wrong, and don't want to alarm the
          user with

        We trap this at the user interface level and feed back a nice error
        to the user.
    '''
    pass

class SendFile(Exception):
    ''' Send a file from the database '''

class SendStaticFile(Exception):
    ''' Send a static file from the instance html directory '''

def initialiseSecurity(security):
    ''' Create some Permissions and Roles on the security object

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
    ''' Instantiate to handle one CGI request.

    See inner_main for request processing.

    Client attributes at instantiation:
        "path" is the PATH_INFO inside the instance (with no leading '/')
        "base" is the base URL for the instance
        "form" is the cgi form, an instance of FieldStorage from the standard
               cgi module
        "additional_headers" is a dictionary of additional HTTP headers that
               should be sent to the client
        "response_code" is the HTTP response code to send to the client

    During the processing of a request, the following attributes are used:
        "error_message" holds a list of error messages
        "ok_message" holds a list of OK messages
        "session" is the current user session id
        "user" is the current user's name
        "userid" is the current user's id
        "template" is the current :template context
        "classname" is the current class context name
        "nodeid" is the current context item id

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

    FV_QUERYNAME = re.compile(r'[@:]queryname')

    # edit form variable handling (see unit tests)
    FV_LABELS = r'''
       ^(
         (?P<note>[@:]note)|
         (?P<file>[@:]file)|
         (
          ((?P<classname>%s)(?P<id>[-\d]+))?  # optional leading designator
          ((?P<required>[@:]required$)|       # :required
           (
            (
             (?P<add>[@:]add[@:])|            # :add:<prop>
             (?P<remove>[@:]remove[@:])|      # :remove:<prop>
             (?P<confirm>[@:]confirm[@:])|    # :confirm:<prop>
             (?P<link>[@:]link[@:])|          # :link:<prop>
             ([@:])                           # just a separator
            )?
            (?P<propname>[^@:]+)             # <prop>
           )
          )
         )
        )$'''

    # Note: index page stuff doesn't appear here:
    # columns, sort, sortdir, filter, group, groupdir, search_text,
    # pagesize, startwith

    def __init__(self, instance, request, env, form=None):
        hyperdb.traceMark()
        self.instance = instance
        self.request = request
        self.env = env

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
        ''' Process a request.

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
            self.classname = None
            self.template = ''
            self.error_message.append(message)
            self.write(self.renderContext())
        except NotFound:
            # pass through
            raise
        except:
            # everything else
            self.write(cgitb.html())

    def clean_sessions(self):
        ''' Age sessions, remove when they haven't been used for a week.
        
            Do it only once an hour.

            Note: also cleans One Time Keys, and other "session" based
            stuff.
        '''
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
        # open the database as admin
        self.opendb('admin')

        # clean age sessions
        self.clean_sessions()

        # make sure we have the session Class
        sessions = self.db.sessions

        # look up the user session cookie
        cookie = Cookie.SimpleCookie(self.env.get('HTTP_COOKIE', ''))
        user = 'anonymous'

        # bump the "revision" of the cookie since the format changed
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
                user = 'anonymous'

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
        ''' Determine the context of this page from the URL:

            The URL path after the instance identifier is examined. The path
            is generally only one entry long.

            - if there is no path, then we are in the "home" context.
            * if the path is "_file", then the additional path entry
              specifies the filename of a static file we're to serve up
              from the instance "html" directory. Raises a SendStaticFile
              exception.
            - if there is something in the path (eg "issue"), it identifies
              the tracker class we're to display.
            - if the path is an item designator (eg "issue123"), then we're
              to display a specific item.
            * if the path starts with an item designator and is longer than
              one entry, then we're assumed to be handling an item of a
              FileClass, and the extra path information gives the filename
              that the client is going to label the download with (ie
              "file123/image.png" is nicer to download than "file123"). This
              raises a SendFile exception.

            Both of the "*" types of contexts stop before we bother to
            determine the template we're going to use. That's because they
            don't actually use templates.

            The template used is specified by the :template CGI variable,
            which defaults to:

             only classname suplied:          "index"
             full item designator supplied:   "item"

            We set:
             self.classname  - the class to display, can be None
             self.template   - the template to render the current context with
             self.nodeid     - the nodeid of the class we're displaying
        '''
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

        # determine the classname and possibly nodeid
        path = self.path.split('/')
        if not path or path[0] in ('', 'home', 'index'):
            if template_override is not None:
                self.template = template_override
            else:
                self.template = ''
            return
        elif path[0] == '_file':
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

        # see if we were passed in a message
        if ok_message:
            self.ok_message.append(ok_message)
        if error_message:
            self.error_message.append(error_message)

    def serve_file(self, designator, dre=re.compile(r'([^\d]+)(\d+)')):
        ''' Serve the file from the content property of the designated item.
        '''
        m = dre.match(str(designator))
        if not m:
            raise NotFound, str(designator)
        classname, nodeid = m.group(1), m.group(2)
        if classname != 'file':
            raise NotFound, designator

        # we just want to serve up the file named
        self.opendb('admin')
        file = self.db.file
        self.additional_headers['Content-Type'] = file.get(nodeid, 'type')
        self.write(file.get(nodeid, 'content'))

    def serve_static_file(self, file):
        ims = None
        # see if there's an if-modified-since...
        if hasattr(self.request, 'headers'):
            ims = self.request.headers.getheader('if-modified-since')
        elif self.env.has_key('HTTP_IF_MODIFIED_SINCE'):
            # cgi will put the header in the env var
            ims = self.env['HTTP_IF_MODIFIED_SINCE']
        filename = os.path.join(self.instance.config.TEMPLATES, file)
        lmt = os.stat(filename)[stat.ST_MTIME]
        if ims:
            ims = rfc822.parsedate(ims)[:6]
            lmtt = time.gmtime(lmt)[:6]
            if lmtt <= ims:
                raise NotModified

        # we just want to serve up the file named
        file = str(file)
        mt = mimetypes.guess_type(file)[0]
        if not mt:
            if file.endswith('.css'):
                mt = 'text/css'
            else:
                mt = 'text/plain'
        self.additional_headers['Content-Type'] = mt
        self.additional_headers['Last-Modifed'] = rfc822.formatdate(lmt)
        self.write(open(filename, 'rb').read())

    def renderContext(self):
        ''' Return a PageTemplate for the named page
        '''
        name = self.classname
        extension = self.template
        pt = Templates(self.instance.config.TEMPLATES).get(name, extension)

        # catch errors so we can handle PT rendering errors more nicely
        args = {
            'ok_message': self.ok_message,
            'error_message': self.error_message
        }
        try:
            # let the template render figure stuff out
            return pt.render(self, None, None, **args)
        except NoTemplate, message:
            return '<strong>%s</strong>'%message
        except:
            # everything else
            return cgitb.pt_html()

    # these are the actions that are available
    actions = (
        ('edit',     'editItemAction'),
        ('editcsv',  'editCSVAction'),
        ('new',      'newItemAction'),
        ('register', 'registerAction'),
        ('confrego', 'confRegoAction'),
        ('passrst',  'passResetAction'),
        ('login',    'loginAction'),
        ('logout',   'logout_action'),
        ('search',   'searchAction'),
        ('retire',   'retireAction'),
        ('show',     'showAction'),
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
            for name, method in self.actions:
                if name == action:
                    break
            else:
                raise ValueError, 'No such action "%s"'%action
            # call the mapped action
            getattr(self, method)()
        except Redirect:
            raise
        except Unauthorised:
            raise

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
        ''' Set up a session cookie for the user and store away the user's
            login info against the session.
        '''
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

    #
    # Actions
    #
    def loginAction(self):
        ''' Attempt to log a user in.

            Sets up a session for the user which contains the login
            credentials.
        '''
        # we need the username at a minimum
        if not self.form.has_key('__login_name'):
            self.error_message.append(_('Username required'))
            return

        # get the login info
        self.user = self.form['__login_name'].value
        if self.form.has_key('__login_password'):
            password = self.form['__login_password'].value
        else:
            password = ''

        # make sure the user exists
        try:
            self.userid = self.db.user.lookup(self.user)
        except KeyError:
            name = self.user
            self.error_message.append(_('No such user "%(name)s"')%locals())
            self.make_user_anonymous()
            return

        # verify the password
        if not self.verifyPassword(self.userid, password):
            self.make_user_anonymous()
            self.error_message.append(_('Incorrect password'))
            return

        # make sure we're allowed to be here
        if not self.loginPermission():
            self.make_user_anonymous()
            self.error_message.append(_("You do not have permission to login"))
            return

        # now we're OK, re-open the database for real, using the user
        self.opendb(self.user)

        # set the session cookie
        self.set_cookie(self.user)

    def verifyPassword(self, userid, password):
        ''' Verify the password that the user has supplied
        '''
        stored = self.db.user.get(self.userid, 'password')
        if password == stored:
            return 1
        if not password and not stored:
            return 1
        return 0

    def loginPermission(self):
        ''' Determine whether the user has permission to log in.

            Base behaviour is to check the user has "Web Access".
        ''' 
        if not self.db.security.hasPermission('Web Access', self.userid):
            return 0
        return 1

    def logout_action(self):
        ''' Make us really anonymous - nuke the cookie too
        '''
        # log us out
        self.make_user_anonymous()

        # construct the logout cookie
        now = Cookie._getdate()
        self.additional_headers['Set-Cookie'] = \
           '%s=deleted; Max-Age=0; expires=%s; Path=%s;'%(self.cookie_name,
            now, self.cookie_path)

        # Let the user know what's going on
        self.ok_message.append(_('You are logged out'))

    def registerAction(self):
        '''Attempt to create a new user based on the contents of the form
        and then set the cookie.

        return 1 on successful login
        '''
        # parse the props from the form
        try:
            props = self.parsePropsFromForm()[0][('user', None)]
        except (ValueError, KeyError), message:
            self.error_message.append(_('Error: ') + str(message))
            return

        # make sure we're allowed to register
        if not self.registerPermission(props):
            raise Unauthorised, _("You do not have permission to register")

        try:
            self.db.user.lookup(props['username'])
            self.error_message.append('Error: A user with the username "%s" '
                'already exists'%props['username'])
            return
        except KeyError:
            pass

        # generate the one-time-key and store the props for later
        otk = ''.join([random.choice(chars) for x in range(32)])
        for propname, proptype in self.db.user.getprops().items():
            value = props.get(propname, None)
            if value is None:
                pass
            elif isinstance(proptype, hyperdb.Date):
                props[propname] = str(value)
            elif isinstance(proptype, hyperdb.Interval):
                props[propname] = str(value)
            elif isinstance(proptype, hyperdb.Password):
                props[propname] = str(value)
        props['__time'] = time.time()
        self.db.otks.set(otk, **props)

        # send the email
        tracker_name = self.db.config.TRACKER_NAME
        subject = 'Complete your registration to %s'%tracker_name
        body = '''
To complete your registration of the user "%(name)s" with %(tracker)s,
please visit the following URL:

   %(url)s?@action=confrego&otk=%(otk)s
'''%{'name': props['username'], 'tracker': tracker_name, 'url': self.base,
                'otk': otk}
        if not self.sendEmail(props['address'], subject, body):
            return

        # commit changes to the database
        self.db.commit()

        # redirect to the "you're almost there" page
        raise Redirect, '%suser?@template=rego_progress'%self.base

    def sendEmail(self, to, subject, content):
        # send email to the user's email address
        message = StringIO.StringIO()
        writer = MimeWriter.MimeWriter(message)
        tracker_name = self.db.config.TRACKER_NAME
        writer.addheader('Subject', encode_header(subject))
        writer.addheader('To', to)
        writer.addheader('From', roundupdb.straddr((tracker_name,
            self.db.config.ADMIN_EMAIL)))
        writer.addheader('Date', time.strftime("%a, %d %b %Y %H:%M:%S +0000",
            time.gmtime()))
        # add a uniquely Roundup header to help filtering
        writer.addheader('X-Roundup-Name', tracker_name)
        # avoid email loops
        writer.addheader('X-Roundup-Loop', 'hello')
        writer.addheader('Content-Transfer-Encoding', 'quoted-printable')
        body = writer.startbody('text/plain; charset=utf-8')

        # message body, encoded quoted-printable
        content = StringIO.StringIO(content)
        quopri.encode(content, body, 0)

        if SENDMAILDEBUG:
            # don't send - just write to a file
            open(SENDMAILDEBUG, 'a').write('FROM: %s\nTO: %s\n%s\n'%(
                self.db.config.ADMIN_EMAIL,
                ', '.join(to),message.getvalue()))
        else:
            # now try to send the message
            try:
                # send the message as admin so bounces are sent there
                # instead of to roundup
                smtp = openSMTPConnection(self.db.config)
                smtp.sendmail(self.db.config.ADMIN_EMAIL, [to],
                    message.getvalue())
            except socket.error, value:
                self.error_message.append("Error: couldn't send email: "
                    "mailhost %s"%value)
                return 0
            except smtplib.SMTPException, msg:
                self.error_message.append("Error: couldn't send email: %s"%msg)
                return 0
        return 1

    def registerPermission(self, props):
        ''' Determine whether the user has permission to register

            Base behaviour is to check the user has "Web Registration".
        '''
        # registration isn't allowed to supply roles
        if props.has_key('roles'):
            return 0
        if self.db.security.hasPermission('Web Registration', self.userid):
            return 1
        return 0

    def confRegoAction(self):
        ''' Grab the OTK, use it to load up the new user details
        '''
        try:
            # pull the rego information out of the otk database
            self.userid = self.db.confirm_registration(self.form['otk'].value)
        except (ValueError, KeyError), message:
            # XXX: we need to make the "default" page be able to display errors!
            self.error_message.append(str(message))
            return
        
        # log the new user in
        self.user = self.db.user.get(self.userid, 'username')
        # re-open the database for real, using the user
        self.opendb(self.user)

        # if we have a session, update it
        if hasattr(self, 'session'):
            self.db.sessions.set(self.session, user=self.user,
                last_use=time.time())
        else:
            # new session cookie
            self.set_cookie(self.user)

        # nice message
        message = _('You are now registered, welcome!')

        # redirect to the user's page
        raise Redirect, '%suser%s?@ok_message=%s'%(self.base,
            self.userid, urllib.quote(message))

    def passResetAction(self):
        ''' Handle password reset requests.

            Presence of either "name" or "address" generate email.
            Presense of "otk" performs the reset.
        '''
        if self.form.has_key('otk'):
            # pull the rego information out of the otk database
            otk = self.form['otk'].value
            uid = self.db.otks.get(otk, 'uid')
            if uid is None:
                self.error_message.append('Invalid One Time Key!')
                return

            # re-open the database as "admin"
            if self.user != 'admin':
                self.opendb('admin')

            # change the password
            newpw = password.generatePassword()

            cl = self.db.user
# XXX we need to make the "default" page be able to display errors!
            try:
                # set the password
                cl.set(uid, password=password.Password(newpw))
                # clear the props from the otk database
                self.db.otks.destroy(otk)
                self.db.commit()
            except (ValueError, KeyError), message:
                self.error_message.append(str(message))
                return

            # user info
            address = self.db.user.get(uid, 'address')
            name = self.db.user.get(uid, 'username')

            # send the email
            tracker_name = self.db.config.TRACKER_NAME
            subject = 'Password reset for %s'%tracker_name
            body = '''
The password has been reset for username "%(name)s".

Your password is now: %(password)s
'''%{'name': name, 'password': newpw}
            if not self.sendEmail(address, subject, body):
                return

            self.ok_message.append('Password reset and email sent to %s'%address)
            return

        # no OTK, so now figure the user
        if self.form.has_key('username'):
            name = self.form['username'].value
            try:
                uid = self.db.user.lookup(name)
            except KeyError:
                self.error_message.append('Unknown username')
                return
            address = self.db.user.get(uid, 'address')
        elif self.form.has_key('address'):
            address = self.form['address'].value
            uid = uidFromAddress(self.db, ('', address), create=0)
            if not uid:
                self.error_message.append('Unknown email address')
                return
            name = self.db.user.get(uid, 'username')
        else:
            self.error_message.append('You need to specify a username '
                'or address')
            return

        # generate the one-time-key and store the props for later
        otk = ''.join([random.choice(chars) for x in range(32)])
        self.db.otks.set(otk, uid=uid, __time=time.time())

        # send the email
        tracker_name = self.db.config.TRACKER_NAME
        subject = 'Confirm reset of password for %s'%tracker_name
        body = '''
Someone, perhaps you, has requested that the password be changed for your
username, "%(name)s". If you wish to proceed with the change, please follow
the link below:

  %(url)suser?@template=forgotten&@action=passrst&otk=%(otk)s

You should then receive another email with the new password.
'''%{'name': name, 'tracker': tracker_name, 'url': self.base, 'otk': otk}
        if not self.sendEmail(address, subject, body):
            return

        self.ok_message.append('Email sent to %s'%address)

    def editItemAction(self):
        ''' Perform an edit of an item in the database.

           See parsePropsFromForm and _editnodes for special variables
        '''
        # parse the props from the form
        try:
            props, links = self.parsePropsFromForm()
        except (ValueError, KeyError), message:
            self.error_message.append(_('Parse Error: ') + str(message))
            return

        # handle the props
        try:
            message = self._editnodes(props, links)
        except (ValueError, KeyError, IndexError), message:
            self.error_message.append(_('Apply Error: ') + str(message))
            return

        # commit now that all the tricky stuff is done
        self.db.commit()

        # redirect to the item's edit page
        raise Redirect, '%s%s%s?@ok_message=%s&@template=%s'%(self.base,
            self.classname, self.nodeid, urllib.quote(message),
            urllib.quote(self.template))

    def editItemPermission(self, props):
        ''' Determine whether the user has permission to edit this item.

            Base behaviour is to check the user can edit this class. If we're
            editing the "user" class, users are allowed to edit their own
            details. Unless it's the "roles" property, which requires the
            special Permission "Web Roles".
        '''
        # if this is a user node and the user is editing their own node, then
        # we're OK
        has = self.db.security.hasPermission
        if self.classname == 'user':
            # reject if someone's trying to edit "roles" and doesn't have the
            # right permission.
            if props.has_key('roles') and not has('Web Roles', self.userid,
                    'user'):
                return 0
            # if the item being edited is the current user, we're ok
            if self.nodeid == self.userid:
                return 1
        if self.db.security.hasPermission('Edit', self.userid, self.classname):
            return 1
        return 0

    def newItemAction(self):
        ''' Add a new item to the database.

            This follows the same form as the editItemAction, with the same
            special form values.
        '''
        # parse the props from the form
        try:
            props, links = self.parsePropsFromForm()
        except (ValueError, KeyError), message:
            self.error_message.append(_('Error: ') + str(message))
            return

        # handle the props - edit or create
        try:
            # when it hits the None element, it'll set self.nodeid
            messages = self._editnodes(props, links)

        except (ValueError, KeyError, IndexError), message:
            # these errors might just be indicative of user dumbness
            self.error_message.append(_('Error: ') + str(message))
            return

        # commit now that all the tricky stuff is done
        self.db.commit()

        # redirect to the new item's page
        raise Redirect, '%s%s%s?@ok_message=%s&@template=%s'%(self.base,
            self.classname, self.nodeid, urllib.quote(messages),
            urllib.quote(self.template))

    def newItemPermission(self, props):
        ''' Determine whether the user has permission to create (edit) this
            item.

            Base behaviour is to check the user can edit this class. No
            additional property checks are made. Additionally, new user items
            may be created if the user has the "Web Registration" Permission.
        '''
        has = self.db.security.hasPermission
        if self.classname == 'user' and has('Web Registration', self.userid,
                'user'):
            return 1
        if has('Edit', self.userid, self.classname):
            return 1
        return 0


    #
    #  Utility methods for editing
    #
    def _editnodes(self, all_props, all_links, newids=None):
        ''' Use the props in all_props to perform edit and creation, then
            use the link specs in all_links to do linking.
        '''
        # figure dependencies and re-work links
        deps = {}
        links = {}
        for cn, nodeid, propname, vlist in all_links:
            if not all_props.has_key((cn, nodeid)):
                # link item to link to doesn't (and won't) exist
                continue
            for value in vlist:
                if not all_props.has_key(value):
                    # link item to link to doesn't (and won't) exist
                    continue
                deps.setdefault((cn, nodeid), []).append(value)
                links.setdefault(value, []).append((cn, nodeid, propname))

        # figure chained dependencies ordering
        order = []
        done = {}
        # loop detection
        change = 0
        while len(all_props) != len(done):
            for needed in all_props.keys():
                if done.has_key(needed):
                    continue
                tlist = deps.get(needed, [])
                for target in tlist:
                    if not done.has_key(target):
                        break
                else:
                    done[needed] = 1
                    order.append(needed)
                    change = 1
            if not change:
                raise ValueError, 'linking must not loop!'

        # now, edit / create
        m = []
        for needed in order:
            props = all_props[needed]
            if not props:
                # nothing to do
                continue
            cn, nodeid = needed

            if nodeid is not None and int(nodeid) > 0:
                # make changes to the node
                props = self._changenode(cn, nodeid, props)

                # and some nice feedback for the user
                if props:
                    info = ', '.join(props.keys())
                    m.append('%s %s %s edited ok'%(cn, nodeid, info))
                else:
                    m.append('%s %s - nothing changed'%(cn, nodeid))
            else:
                assert props

                # make a new node
                newid = self._createnode(cn, props)
                if nodeid is None:
                    self.nodeid = newid
                nodeid = newid

                # and some nice feedback for the user
                m.append('%s %s created'%(cn, newid))

            # fill in new ids in links
            if links.has_key(needed):
                for linkcn, linkid, linkprop in links[needed]:
                    props = all_props[(linkcn, linkid)]
                    cl = self.db.classes[linkcn]
                    propdef = cl.getprops()[linkprop]
                    if not props.has_key(linkprop):
                        if linkid is None or linkid.startswith('-'):
                            # linking to a new item
                            if isinstance(propdef, hyperdb.Multilink):
                                props[linkprop] = [newid]
                            else:
                                props[linkprop] = newid
                        else:
                            # linking to an existing item
                            if isinstance(propdef, hyperdb.Multilink):
                                existing = cl.get(linkid, linkprop)[:]
                                existing.append(nodeid)
                                props[linkprop] = existing
                            else:
                                props[linkprop] = newid

        return '<br>'.join(m)

    def _changenode(self, cn, nodeid, props):
        ''' change the node based on the contents of the form
        '''
        # check for permission
        if not self.editItemPermission(props):
            raise Unauthorised, 'You do not have permission to edit %s'%cn

        # make the changes
        cl = self.db.classes[cn]
        return cl.set(nodeid, **props)

    def _createnode(self, cn, props):
        ''' create a node based on the contents of the form
        '''
        # check for permission
        if not self.newItemPermission(props):
            raise Unauthorised, 'You do not have permission to create %s'%cn

        # create the node and return its id
        cl = self.db.classes[cn]
        return cl.create(**props)

    # 
    # More actions
    #
    def editCSVAction(self):
        ''' Performs an edit of all of a class' items in one go.

            The "rows" CGI var defines the CSV-formatted entries for the
            class. New nodes are identified by the ID 'X' (or any other
            non-existent ID) and removed lines are retired.
        '''
        # this is per-class only
        if not self.editCSVPermission():
            self.error_message.append(
                _('You do not have permission to edit %s' %self.classname))

        # get the CSV module
        if rcsv.error:
            self.error_message.append(_(rcsv.error))
            return

        cl = self.db.classes[self.classname]
        idlessprops = cl.getprops(protected=0).keys()
        idlessprops.sort()
        props = ['id'] + idlessprops

        # do the edit
        rows = StringIO.StringIO(self.form['rows'].value)
        reader = rcsv.reader(rows, rcsv.comma_separated)
        found = {}
        line = 0
        for values in reader:
            line += 1
            if line == 1: continue
            # skip property names header
            if values == props:
                continue

            # extract the nodeid
            nodeid, values = values[0], values[1:]
            found[nodeid] = 1

            # see if the node exists
            if nodeid in ('x', 'X') or not cl.hasnode(nodeid):
                exists = 0
            else:
                exists = 1

            # confirm correct weight
            if len(idlessprops) != len(values):
                self.error_message.append(
                    _('Not enough values on line %(line)s')%{'line':line})
                return

            # extract the new values
            d = {}
            for name, value in zip(idlessprops, values):
                prop = cl.properties[name]
                value = value.strip()
                # only add the property if it has a value
                if value:
                    # if it's a multilink, split it
                    if isinstance(prop, hyperdb.Multilink):
                        value = value.split(':')
                    elif isinstance(prop, hyperdb.Password):
                        value = password.Password(value)
                    elif isinstance(prop, hyperdb.Interval):
                        value = date.Interval(value)
                    elif isinstance(prop, hyperdb.Date):
                        value = date.Date(value)
                    elif isinstance(prop, hyperdb.Boolean):
                        value = value.lower() in ('yes', 'true', 'on', '1')
                    elif isinstance(prop, hyperdb.Number):
                        value = float(value)
                    d[name] = value
                elif exists:
                    # nuke the existing value
                    if isinstance(prop, hyperdb.Multilink):
                        d[name] = []
                    else:
                        d[name] = None

            # perform the edit
            if exists:
                # edit existing
                cl.set(nodeid, **d)
            else:
                # new node
                found[cl.create(**d)] = 1

        # retire the removed entries
        for nodeid in cl.list():
            if not found.has_key(nodeid):
                cl.retire(nodeid)

        # all OK
        self.db.commit()

        self.ok_message.append(_('Items edited OK'))

    def editCSVPermission(self):
        ''' Determine whether the user has permission to edit this class.

            Base behaviour is to check the user can edit this class.
        ''' 
        if not self.db.security.hasPermission('Edit', self.userid,
                self.classname):
            return 0
        return 1

    def searchAction(self, wcre=re.compile(r'[\s,]+')):
        ''' Mangle some of the form variables.

            Set the form ":filter" variable based on the values of the
            filter variables - if they're set to anything other than
            "dontcare" then add them to :filter.

            Handle the ":queryname" variable and save off the query to
            the user's query list.

            Split any String query values on whitespace and comma.
        '''
        # generic edit is per-class only
        if not self.searchPermission():
            self.error_message.append(
                _('You do not have permission to search %s' %self.classname))

        # add a faked :filter form variable for each filtering prop
        props = self.db.classes[self.classname].getprops()
        queryname = ''
        for key in self.form.keys():
            # special vars
            if self.FV_QUERYNAME.match(key):
                queryname = self.form[key].value.strip()
                continue

            if not props.has_key(key):
                continue
            if isinstance(self.form[key], type([])):
                # search for at least one entry which is not empty
                for minifield in self.form[key]:
                    if minifield.value:
                        break
                else:
                    continue
            else:
                if not self.form[key].value:
                    continue
                if isinstance(props[key], hyperdb.String):
                    v = self.form[key].value
                    l = token.token_split(v)
                    if len(l) > 1 or l[0] != v:
                        self.form.value.remove(self.form[key])
                        # replace the single value with the split list
                        for v in l:
                            self.form.value.append(cgi.MiniFieldStorage(key, v))

            self.form.value.append(cgi.MiniFieldStorage('@filter', key))

        # handle saving the query params
        if queryname:
            # parse the environment and figure what the query _is_
            req = HTMLRequest(self)

            # The [1:] strips off the '?' character, it isn't part of the
            # query string.
            url = req.indexargs_href('', {})[1:]

            # handle editing an existing query
            try:
                qid = self.db.query.lookup(queryname)
                self.db.query.set(qid, klass=self.classname, url=url)
            except KeyError:
                # create a query
                qid = self.db.query.create(name=queryname,
                    klass=self.classname, url=url)

                # and add it to the user's query multilink
                queries = self.db.user.get(self.userid, 'queries')
                queries.append(qid)
                self.db.user.set(self.userid, queries=queries)

            # commit the query change to the database
            self.db.commit()

    def searchPermission(self):
        ''' Determine whether the user has permission to search this class.

            Base behaviour is to check the user can view this class.
        ''' 
        if not self.db.security.hasPermission('View', self.userid,
                self.classname):
            return 0
        return 1


    def retireAction(self):
        ''' Retire the context item.
        '''
        # if we want to view the index template now, then unset the nodeid
        # context info (a special-case for retire actions on the index page)
        nodeid = self.nodeid
        if self.template == 'index':
            self.nodeid = None

        # generic edit is per-class only
        if not self.retirePermission():
            self.error_message.append(
                _('You do not have permission to retire %s' %self.classname))
            return

        # make sure we don't try to retire admin or anonymous
        if self.classname == 'user' and \
                self.db.user.get(nodeid, 'username') in ('admin', 'anonymous'):
            self.error_message.append(
                _('You may not retire the admin or anonymous user'))
            return

        # do the retire
        self.db.getclass(self.classname).retire(nodeid)
        self.db.commit()

        self.ok_message.append(
            _('%(classname)s %(itemid)s has been retired')%{
                'classname': self.classname.capitalize(), 'itemid': nodeid})

    def retirePermission(self):
        ''' Determine whether the user has permission to retire this class.

            Base behaviour is to check the user can edit this class.
        ''' 
        if not self.db.security.hasPermission('Edit', self.userid,
                self.classname):
            return 0
        return 1


    def showAction(self, typere=re.compile('[@:]type'),
            numre=re.compile('[@:]number')):
        ''' Show a node of a particular class/id
        '''
        t = n = ''
        for key in self.form.keys():
            if typere.match(key):
                t = self.form[key].value.strip()
            elif numre.match(key):
                n = self.form[key].value.strip()
        if not t:
            raise ValueError, 'Invalid %s number'%t
        url = '%s%s%s'%(self.db.config.TRACKER_WEB, t, n)
        raise Redirect, url

    def parsePropsFromForm(self, num_re=re.compile('^\d+$')):
        ''' Item properties and their values are edited with html FORM
            variables and their values. You can:

            - Change the value of some property of the current item.
            - Create a new item of any class, and edit the new item's
              properties,
            - Attach newly created items to a multilink property of the
              current item.
            - Remove items from a multilink property of the current item.
            - Specify that some properties are required for the edit
              operation to be successful.

            In the following, <bracketed> values are variable, "@" may be
            either ":" or "@", and other text "required" is fixed.

            Most properties are specified as form variables:

             <propname>
              - property on the current context item

             <designator>"@"<propname>
              - property on the indicated item (for editing related
                information)

            Designators name a specific item of a class.

            <classname><N>

                Name an existing item of class <classname>.

            <classname>"-"<N>

                Name the <N>th new item of class <classname>. If the form
                submission is successful, a new item of <classname> is
                created. Within the submitted form, a particular
                designator of this form always refers to the same new
                item.

            Once we have determined the "propname", we look at it to see
            if it's special:

            @required
                The associated form value is a comma-separated list of
                property names that must be specified when the form is
                submitted for the edit operation to succeed.  

                When the <designator> is missing, the properties are
                for the current context item.  When <designator> is
                present, they are for the item specified by
                <designator>.

                The "@required" specifier must come before any of the
                properties it refers to are assigned in the form.

            @remove@<propname>=id(s) or @add@<propname>=id(s)
                The "@add@" and "@remove@" edit actions apply only to
                Multilink properties.  The form value must be a
                comma-separate list of keys for the class specified by
                the simple form variable.  The listed items are added
                to (respectively, removed from) the specified
                property.

            @link@<propname>=<designator>
                If the edit action is "@link@", the simple form
                variable must specify a Link or Multilink property.
                The form value is a comma-separated list of
                designators.  The item corresponding to each
                designator is linked to the property given by simple
                form variable.  These are collected up and returned in
                all_links.

            None of the above (ie. just a simple form value)
                The value of the form variable is converted
                appropriately, depending on the type of the property.

                For a Link('klass') property, the form value is a
                single key for 'klass', where the key field is
                specified in dbinit.py.  

                For a Multilink('klass') property, the form value is a
                comma-separated list of keys for 'klass', where the
                key field is specified in dbinit.py.  

                Note that for simple-form-variables specifiying Link
                and Multilink properties, the linked-to class must
                have a key field.

                For a String() property specifying a filename, the
                file named by the form value is uploaded. This means we
                try to set additional properties "filename" and "type" (if
                they are valid for the class).  Otherwise, the property
                is set to the form value.

                For Date(), Interval(), Boolean(), and Number()
                properties, the form value is converted to the
                appropriate

            Any of the form variables may be prefixed with a classname or
            designator.

            Two special form values are supported for backwards
            compatibility:

            @note
                This is equivalent to::

                    @link@messages=msg-1
                    @msg-1@content=value

                except that in addition, the "author" and "date"
                properties of "msg-1" are set to the userid of the
                submitter, and the current time, respectively.

            @file
                This is equivalent to::

                    @link@files=file-1
                    @file-1@content=value

                The String content value is handled as described above for
                file uploads.

            If both the "@note" and "@file" form variables are
            specified, the action::

                    @link@msg-1@files=file-1

            is also performed.

            We also check that FileClass items have a "content" property with
            actual content, otherwise we remove them from all_props before
            returning.

            The return from this method is a dict of 
                (classname, id): properties
            ... this dict _always_ has an entry for the current context,
            even if it's empty (ie. a submission for an existing issue that
            doesn't result in any changes would return {('issue','123'): {}})
            The id may be None, which indicates that an item should be
            created.
        '''
        # some very useful variables
        db = self.db
        form = self.form

        if not hasattr(self, 'FV_SPECIAL'):
            # generate the regexp for handling special form values
            classes = '|'.join(db.classes.keys())
            # specials for parsePropsFromForm
            # handle the various forms (see unit tests)
            self.FV_SPECIAL = re.compile(self.FV_LABELS%classes, re.VERBOSE)
            self.FV_DESIGNATOR = re.compile(r'(%s)([-\d]+)'%classes)

        # these indicate the default class / item
        default_cn = self.classname
        default_cl = self.db.classes[default_cn]
        default_nodeid = self.nodeid

        # we'll store info about the individual class/item edit in these
        all_required = {}       # required props per class/item
        all_props = {}          # props to set per class/item
        got_props = {}          # props received per class/item
        all_propdef = {}        # note - only one entry per class
        all_links = []          # as many as are required

        # we should always return something, even empty, for the context
        all_props[(default_cn, default_nodeid)] = {}

        keys = form.keys()
        timezone = db.getUserTimezone()

        # sentinels for the :note and :file props
        have_note = have_file = 0

        # extract the usable form labels from the form
        matches = []
        for key in keys:
            m = self.FV_SPECIAL.match(key)
            if m:
                matches.append((key, m.groupdict()))

        # now handle the matches
        for key, d in matches:
            if d['classname']:
                # we got a designator
                cn = d['classname']
                cl = self.db.classes[cn]
                nodeid = d['id']
                propname = d['propname']
            elif d['note']:
                # the special note field
                cn = 'msg'
                cl = self.db.classes[cn]
                nodeid = '-1'
                propname = 'content'
                all_links.append((default_cn, default_nodeid, 'messages',
                    [('msg', '-1')]))
                have_note = 1
            elif d['file']:
                # the special file field
                cn = 'file'
                cl = self.db.classes[cn]
                nodeid = '-1'
                propname = 'content'
                all_links.append((default_cn, default_nodeid, 'files',
                    [('file', '-1')]))
                have_file = 1
            else:
                # default
                cn = default_cn
                cl = default_cl
                nodeid = default_nodeid
                propname = d['propname']

            # the thing this value relates to is...
            this = (cn, nodeid)

            # get more info about the class, and the current set of
            # form props for it
            if not all_propdef.has_key(cn):
                all_propdef[cn] = cl.getprops()
            propdef = all_propdef[cn]
            if not all_props.has_key(this):
                all_props[this] = {}
            props = all_props[this]
            if not got_props.has_key(this):
                got_props[this] = {}

            # is this a link command?
            if d['link']:
                value = []
                for entry in extractFormList(form[key]):
                    m = self.FV_DESIGNATOR.match(entry)
                    if not m:
                        raise ValueError, \
                            'link "%s" value "%s" not a designator'%(key, entry)
                    value.append((m.group(1), m.group(2)))

                # make sure the link property is valid
                if (not isinstance(propdef[propname], hyperdb.Multilink) and
                        not isinstance(propdef[propname], hyperdb.Link)):
                    raise ValueError, '%s %s is not a link or '\
                        'multilink property'%(cn, propname)

                all_links.append((cn, nodeid, propname, value))
                continue

            # detect the special ":required" variable
            if d['required']:
                all_required[this] = extractFormList(form[key])
                continue

            # see if we're performing a special multilink action
            mlaction = 'set'
            if d['remove']:
                mlaction = 'remove'
            elif d['add']:
                mlaction = 'add'

            # does the property exist?
            if not propdef.has_key(propname):
                if mlaction != 'set':
                    raise ValueError, 'You have submitted a %s action for'\
                        ' the property "%s" which doesn\'t exist'%(mlaction,
                        propname)
                # the form element is probably just something we don't care
                # about - ignore it
                continue
            proptype = propdef[propname]

            # Get the form value. This value may be a MiniFieldStorage or a list
            # of MiniFieldStorages.
            value = form[key]

            # handle unpacking of the MiniFieldStorage / list form value
            if isinstance(proptype, hyperdb.Multilink):
                value = extractFormList(value)
            else:
                # multiple values are not OK
                if isinstance(value, type([])):
                    raise ValueError, 'You have submitted more than one value'\
                        ' for the %s property'%propname
                # value might be a file upload...
                if not hasattr(value, 'filename') or value.filename is None:
                    # nope, pull out the value and strip it
                    value = value.value.strip()

            # now that we have the props field, we need a teensy little
            # extra bit of help for the old :note field...
            if d['note'] and value:
                props['author'] = self.db.getuid()
                props['date'] = date.Date()

            # handle by type now
            if isinstance(proptype, hyperdb.Password):
                if not value:
                    # ignore empty password values
                    continue
                for key, d in matches:
                    if d['confirm'] and d['propname'] == propname:
                        confirm = form[key]
                        break
                else:
                    raise ValueError, 'Password and confirmation text do '\
                        'not match'
                if isinstance(confirm, type([])):
                    raise ValueError, 'You have submitted more than one value'\
                        ' for the %s property'%propname
                if value != confirm.value:
                    raise ValueError, 'Password and confirmation text do '\
                        'not match'
                value = password.Password(value)

            elif isinstance(proptype, hyperdb.Link):
                # see if it's the "no selection" choice
                if value == '-1' or not value:
                    # if we're creating, just don't include this property
                    if not nodeid or nodeid.startswith('-'):
                        continue
                    value = None
                else:
                    # handle key values
                    link = proptype.classname
                    if not num_re.match(value):
                        try:
                            value = db.classes[link].lookup(value)
                        except KeyError:
                            raise ValueError, _('property "%(propname)s": '
                                '%(value)s not a %(classname)s')%{
                                'propname': propname, 'value': value,
                                'classname': link}
                        except TypeError, message:
                            raise ValueError, _('you may only enter ID values '
                                'for property "%(propname)s": %(message)s')%{
                                'propname': propname, 'message': message}
            elif isinstance(proptype, hyperdb.Multilink):
                # perform link class key value lookup if necessary
                link = proptype.classname
                link_cl = db.classes[link]
                l = []
                for entry in value:
                    if not entry: continue
                    if not num_re.match(entry):
                        try:
                            entry = link_cl.lookup(entry)
                        except KeyError:
                            raise ValueError, _('property "%(propname)s": '
                                '"%(value)s" not an entry of %(classname)s')%{
                                'propname': propname, 'value': entry,
                                'classname': link}
                        except TypeError, message:
                            raise ValueError, _('you may only enter ID values '
                                'for property "%(propname)s": %(message)s')%{
                                'propname': propname, 'message': message}
                    l.append(entry)
                l.sort()

                # now use that list of ids to modify the multilink
                if mlaction == 'set':
                    value = l
                else:
                    # we're modifying the list - get the current list of ids
                    if props.has_key(propname):
                        existing = props[propname]
                    elif nodeid and not nodeid.startswith('-'):
                        existing = cl.get(nodeid, propname, [])
                    else:
                        existing = []

                    # now either remove or add
                    if mlaction == 'remove':
                        # remove - handle situation where the id isn't in
                        # the list
                        for entry in l:
                            try:
                                existing.remove(entry)
                            except ValueError:
                                raise ValueError, _('property "%(propname)s": '
                                    '"%(value)s" not currently in list')%{
                                    'propname': propname, 'value': entry}
                    else:
                        # add - easy, just don't dupe
                        for entry in l:
                            if entry not in existing:
                                existing.append(entry)
                    value = existing
                    value.sort()

            elif value == '':
                # if we're creating, just don't include this property
                if not nodeid or nodeid.startswith('-'):
                    continue
                # other types should be None'd if there's no value
                value = None
            else:
                # handle ValueErrors for all these in a similar fashion
                try:
                    if isinstance(proptype, hyperdb.String):
                        if (hasattr(value, 'filename') and
                                value.filename is not None):
                            # skip if the upload is empty
                            if not value.filename:
                                continue
                            # this String is actually a _file_
                            # try to determine the file content-type
                            fn = value.filename.split('\\')[-1]
                            if propdef.has_key('name'):
                                props['name'] = fn
                            # use this info as the type/filename properties
                            if propdef.has_key('type'):
                                props['type'] = mimetypes.guess_type(fn)[0]
                                if not props['type']:
                                    props['type'] = "application/octet-stream"
                            # finally, read the content
                            value = value.value
                        else:
                            # normal String fix the CRLF/CR -> LF stuff
                            value = fixNewlines(value)

                    elif isinstance(proptype, hyperdb.Date):
                        value = date.Date(value, offset=timezone)
                    elif isinstance(proptype, hyperdb.Interval):
                        value = date.Interval(value)
                    elif isinstance(proptype, hyperdb.Boolean):
                        value = value.lower() in ('yes', 'true', 'on', '1')
                    elif isinstance(proptype, hyperdb.Number):
                        value = float(value)
                except ValueError, msg:
                    raise ValueError, _('Error with %s property: %s')%(
                        propname, msg)

            # register that we got this property
            if value:
                got_props[this][propname] = 1

            # get the old value
            if nodeid and not nodeid.startswith('-'):
                try:
                    existing = cl.get(nodeid, propname)
                except KeyError:
                    # this might be a new property for which there is
                    # no existing value
                    if not propdef.has_key(propname):
                        raise

                # make sure the existing multilink is sorted
                if isinstance(proptype, hyperdb.Multilink):
                    existing.sort()

                # "missing" existing values may not be None
                if not existing:
                    if isinstance(proptype, hyperdb.String) and not existing:
                        # some backends store "missing" Strings as empty strings
                        existing = None
                    elif isinstance(proptype, hyperdb.Number) and not existing:
                        # some backends store "missing" Numbers as 0 :(
                        existing = 0
                    elif isinstance(proptype, hyperdb.Boolean) and not existing:
                        # likewise Booleans
                        existing = 0

                # if changed, set it
                if value != existing:
                    props[propname] = value
            else:
                # don't bother setting empty/unset values
                if value is None:
                    continue
                elif isinstance(proptype, hyperdb.Multilink) and value == []:
                    continue
                elif isinstance(proptype, hyperdb.String) and value == '':
                    continue

                props[propname] = value

        # check to see if we need to specially link a file to the note
        if have_note and have_file:
            all_links.append(('msg', '-1', 'files', [('file', '-1')]))

        # see if all the required properties have been supplied
        s = []
        for thing, required in all_required.items():
            # register the values we got
            got = got_props.get(thing, {})
            for entry in required[:]:
                if got.has_key(entry):
                    required.remove(entry)

            # any required values not present?
            if not required:
                continue

            # tell the user to entry the values required
            if len(required) > 1:
                p = 'properties'
            else:
                p = 'property'
            s.append('Required %s %s %s not supplied'%(thing[0], p,
                ', '.join(required)))
        if s:
            raise ValueError, '\n'.join(s)

        # When creating a FileClass node, it should have a non-empty content
        # property to be created. When editing a FileClass node, it should
        # either have a non-empty content property or no property at all. In
        # the latter case, nothing will change.
        for (cn, id), props in all_props.items():
            if isinstance(self.db.classes[cn], hyperdb.FileClass):
                if id == '-1':
                      if not props.get('content', ''):
                            del all_props[(cn, id)]
                elif props.has_key('content') and not props['content']:
                      raise ValueError, _('File is empty')
        return all_props, all_links

def fixNewlines(text):
    ''' Homogenise line endings.

        Different web clients send different line ending values, but
        other systems (eg. email) don't necessarily handle those line
        endings. Our solution is to convert all line endings to LF.
    '''
    text = text.replace('\r\n', '\n')
    return text.replace('\r', '\n')

def extractFormList(value):
    ''' Extract a list of values from the form value.

        It may be one of:
         [MiniFieldStorage('value'), MiniFieldStorage('value','value',...), ...]
         MiniFieldStorage('value,value,...')
         MiniFieldStorage('value')
    '''
    # multiple values are OK
    if isinstance(value, type([])):
        # it's a list of MiniFieldStorages - join then into
        values = ','.join([i.value.strip() for i in value])
    else:
        # it's a MiniFieldStorage, but may be a comma-separated list
        # of values
        values = value.value

    value = [i.strip() for i in values.split(',')]

    # filter out the empty bits
    return filter(None, value)

