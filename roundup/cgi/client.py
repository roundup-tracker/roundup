# $Id: client.py,v 1.65.2.13 2003-06-24 05:19:10 richard Exp $

__doc__ = """
WWW request handler (also used in the stand-alone server).
"""

import os, os.path, cgi, StringIO, urlparse, re, traceback, mimetypes, urllib
import binascii, Cookie, time, random, rfc822, stat

from roundup import roundupdb, date, hyperdb, password
from roundup.i18n import _

from roundup.cgi.templating import Templates, HTMLRequest, NoTemplate
from roundup.cgi import cgitb

from roundup.cgi.PageTemplates import PageTemplate

class Unauthorised(ValueError):
    pass

class NotFound(ValueError):
    pass

class Redirect(Exception):
    pass

class NotModified(Exception):
    pass

class SendFile(Exception):
    ' Sent a file from the database '

class SendStaticFile(Exception):
    ' Send a static file from the instance html directory '

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
    '''

    def __init__(self, instance, request, env, form=None):
        hyperdb.traceMark()
        self.instance = instance
        self.request = request
        self.env = env

        # save off the path
        self.path = env['PATH_INFO']

        # this is the base URL for this instance
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
            self.additional_headers['Pragma'] = 'no-cache'
            self.additional_headers['Expires'] = 'Thu, 1 Jan 1970 00:00:00 GMT'

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
            self.classname=None
            self.template=''
            self.error_message.append(message)
            self.write(self.renderContext())
        except NotFound:
            # pass through
            raise
        except:
            # everything else
            self.write(cgitb.html())

    def determine_user(self):
        ''' Determine who the user is
        '''
        # make sure the db is open
        self.opendb('admin')

        # clean age sessions
        self.clean_sessions()

        # make sure we have the session Class
        sessions = self.db.sessions

        # look up the user session cookie
        cookie = Cookie.Cookie(self.env.get('HTTP_COOKIE', ''))
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

    def clean_sessions(self):
        ''' Age sessions, remove when they haven't been used for a week.
                
            Do it only once an hour.
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
            sessions.set('last_clean', last_use=time.time())

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

        # determine the classname and possibly nodeid
        path = self.path.split('/')
        if not path or path[0] in ('', 'home', 'index'):
            if self.form.has_key(':template'):
                self.template = self.form[':template'].value
            else:
                self.template = ''
            return
        elif path[0] == '_file':
            raise SendStaticFile, path[1]
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
        if self.form.has_key(':template'):
            self.template = self.form[':template'].value

        # see if we were passed in a message
        if self.form.has_key(':ok_message'):
            msg = clean_message(self.form[':ok_message'].value)
            self.ok_message.append(msg)
        if self.form.has_key(':error_message'):
            msg = clean_message(self.form[':error_message'].value)
            self.error_message.append(msg)

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
        ('editCSV',  'editCSVAction'),
        ('new',      'newItemAction'),
        ('register', 'registerAction'),
        ('login',    'loginAction'),
        ('logout',   'logout_action'),
        ('search',   'searchAction'),
        ('retire',   'retireAction'),
    )
    def handle_action(self):
        ''' Determine whether there should be an _action called.

            The action is defined by the form variable :action which
            identifies the method on this object to call. The four basic
            actions are defined in the "actions" sequence on this class:
             "edit"      -> self.editItemAction
             "new"       -> self.newItemAction
             "register"  -> self.registerAction
             "login"     -> self.loginAction
             "logout"    -> self.logout_action
             "search"    -> self.searchAction
             "retire"    -> self.retireAction
        '''
        if not self.form.has_key(':action'):
            return None
        try:
            # get the action, validate it
            action = self.form[':action'].value
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
        except:
            self.db.rollback()
            s = StringIO.StringIO()
            traceback.print_exc(None, s)
            self.error_message.append('<pre>%s</pre>'%cgi.escape(s.getvalue()))

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
        # create the new user
        cl = self.db.user

        # parse the props from the form
        try:
            props = parsePropsFromForm(self.db, cl, self.form, self.nodeid)
        except (ValueError, KeyError), message:
            self.error_message.append(_('Error: ') + str(message))
            return

        # make sure we're allowed to register
        if not self.registerPermission(props):
            raise Unauthorised, _("You do not have permission to register")

        # re-open the database as "admin"
        if self.user != 'admin':
            self.opendb('admin')
            
        # create the new user
        cl = self.db.user
        try:
            props = parsePropsFromForm(self.db, cl, self.form)
            props['roles'] = self.instance.config.NEW_WEB_USER_ROLES
            self.userid = cl.create(**props)
            self.db.commit()
        except (ValueError, KeyError), message:
            self.error_message.append(message)
            return

        # log the new user in
        self.user = cl.get(self.userid, 'username')
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

        # redirect to the item's edit page
        raise Redirect, '%s%s%s?:ok_message=%s'%(
            self.base, self.classname, self.userid,  urllib.quote(message))

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

    def editItemAction(self):
        ''' Perform an edit of an item in the database.

            Some special form elements:

            :link=designator:property
            :multilink=designator:property
             The value specifies a node designator and the property on that
             node to add _this_ node to as a link or multilink.
            :note
             Create a message and attach it to the current node's
             "messages" property.
            :file
             Create a file and attach it to the current node's
             "files" property. Attach the file to the message created from
             the :note if it's supplied.

            :required=property,property,...
             The named properties are required to be filled in the form.

            :remove:<propname>=id(s)
             The ids will be removed from the multilink property.
            :add:<propname>=id(s)
             The ids will be added to the multilink property.

        '''
        cl = self.db.classes[self.classname]

        # parse the props from the form
        try:
            props = parsePropsFromForm(self.db, cl, self.form, self.nodeid)
        except (ValueError, KeyError), message:
            self.error_message.append(_('Error: ') + str(message))
            return

        # check permission
        if not self.editItemPermission(props):
            self.error_message.append(
                _('You do not have permission to edit %(classname)s'%
                self.__dict__))
            return

        # perform the edit
        try:
            # make changes to the node
            props = self._changenode(props)
            # handle linked nodes 
            self._post_editnode(self.nodeid)
        except (ValueError, KeyError, IndexError), message:
            self.error_message.append(_('Error: ') + str(message))
            return

        # commit now that all the tricky stuff is done
        self.db.commit()

        # and some nice feedback for the user
        if props:
            message = _('%(changes)s edited ok')%{'changes':
                ', '.join(props.keys())}
        elif self.form.has_key(':note') and self.form[':note'].value:
            message = _('note added')
        elif (self.form.has_key(':file') and self.form[':file'].filename):
            message = _('file added')
        else:
            message = _('nothing changed')

        # redirect to the item's edit page
        raise Redirect, '%s%s%s?:ok_message=%s'%(self.base, self.classname,
            self.nodeid,  urllib.quote(message))

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
        cl = self.db.classes[self.classname]

        # parse the props from the form
        try:
            props = parsePropsFromForm(self.db, cl, self.form, self.nodeid)
        except (ValueError, KeyError), message:
            self.error_message.append(_('Error: ') + str(message))
            return

        if not self.newItemPermission(props):
            self.error_message.append(
                _('You do not have permission to create %s' %self.classname))

        # create a little extra message for anticipated :link / :multilink
        if self.form.has_key(':multilink'):
            link = self.form[':multilink'].value
        elif self.form.has_key(':link'):
            link = self.form[':multilink'].value
        else:
            link = None
            xtra = ''
        if link:
            designator, linkprop = link.split(':')
            xtra = ' for <a href="%s">%s</a>'%(designator, designator)

        try:
            # do the create
            nid = self._createnode(props)
        except (ValueError, KeyError, IndexError), message:
            # these errors might just be indicative of user dumbness
            self.error_message.append(_('Error: ') + str(message))
            return
        except:
            # oops
            self.db.rollback()
            s = StringIO.StringIO()
            traceback.print_exc(None, s)
            self.error_message.append('<pre>%s</pre>'%cgi.escape(s.getvalue()))
            return

        try:
            # handle linked nodes 
            self._post_editnode(nid)

            # commit now that all the tricky stuff is done
            self.db.commit()

            # render the newly created item
            self.nodeid = nid

            # and some nice feedback for the user
            message = _('%(classname)s created ok')%self.__dict__ + xtra
        except:
            # oops
            self.db.rollback()
            s = StringIO.StringIO()
            traceback.print_exc(None, s)
            self.error_message.append('<pre>%s</pre>'%cgi.escape(s.getvalue()))
            return

        # redirect to the new item's page
        raise Redirect, '%s%s%s?:ok_message=%s'%(self.base, self.classname,
            nid,  urllib.quote(message))

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
        try:
            import csv
        except ImportError:
            self.error_message.append(_(
                'Sorry, you need the csv module to use this function.<br>\n'
                'Get it from: <a href="http://www.object-craft.com.au/projects/csv/">http://www.object-craft.com.au/projects/csv/'))
            return

        cl = self.db.classes[self.classname]
        idlessprops = cl.getprops(protected=0).keys()
        idlessprops.sort()
        props = ['id'] + idlessprops

        # do the edit
        rows = self.form['rows'].value.splitlines()
        p = csv.parser()
        found = {}
        line = 0
        for row in rows[1:]:
            line += 1
            values = p.parse(row)
            # not a complete row, keep going
            if not values: continue

            # skip property names header
            if values == props:
                continue

            # extract the nodeid
            nodeid, values = values[0], values[1:]
            found[nodeid] = 1

            # see if the node exists
            if cl.hasnode(nodeid):
                exists = 1
            else:
                exists = 0

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

    def searchAction(self):
        ''' Mangle some of the form variables.

            Set the form ":filter" variable based on the values of the
            filter variables - if they're set to anything other than
            "dontcare" then add them to :filter.

            Also handle the ":queryname" variable and save off the query to
            the user's query list.
        '''
        # generic edit is per-class only
        if not self.searchPermission():
            self.error_message.append(
                _('You do not have permission to search %s' %self.classname))

        # add a faked :filter form variable for each filtering prop
        props = self.db.classes[self.classname].getprops()
        for key in self.form.keys():
            if not props.has_key(key): continue
            if isinstance(self.form[key], type([])):
                # search for at least one entry which is not empty
                for minifield in self.form[key]:
                    if minifield.value:
                        break
                else:
                    continue
            else:
                if not self.form[key].value: continue
            self.form.value.append(cgi.MiniFieldStorage(':filter', key))

        # handle saving the query params
        if self.form.has_key(':queryname'):
            queryname = self.form[':queryname'].value.strip()
            if queryname:
                # parse the environment and figure what the query _is_
                req = HTMLRequest(self)
                url = req.indexargs_href('', {})

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


    #
    #  Utility methods for editing
    #
    def _changenode(self, props):
        ''' change the node based on the contents of the form
        '''
        cl = self.db.classes[self.classname]

        # create the message
        message, files = self._handle_message()
        if message:
            props['messages'] = cl.get(self.nodeid, 'messages') + [message]
        if files:
            props['files'] = cl.get(self.nodeid, 'files') + files

        # make the changes
        return cl.set(self.nodeid, **props)

    def _createnode(self, props):
        ''' create a node based on the contents of the form
        '''
        cl = self.db.classes[self.classname]

        # check for messages and files
        message, files = self._handle_message()
        if message:
            props['messages'] = [message]
        if files:
            props['files'] = files
        # create the node and return it's id
        return cl.create(**props)

    def _handle_message(self):
        ''' generate an edit message
        '''
        # handle file attachments 
        files = []
        if self.form.has_key(':file'):
            file = self.form[':file']
            if file.filename:
                filename = file.filename.split('\\')[-1]
                mime_type = mimetypes.guess_type(filename)[0]
                if not mime_type:
                    mime_type = "application/octet-stream"
                # create the new file entry
                files.append(self.db.file.create(type=mime_type,
                    name=filename, content=file.file.read()))

        # we don't want to do a message if none of the following is true...
        cn = self.classname
        cl = self.db.classes[self.classname]
        props = cl.getprops()
        note = None
        # in a nutshell, don't do anything if there's no note or there's no
        # NOSY
        if self.form.has_key(':note'):
            # fix the CRLF/CR -> LF stuff
            note = fixNewlines(self.form[':note'].value.strip())
        if not note:
            return None, files
        if not props.has_key('messages'):
            return None, files
        if not isinstance(props['messages'], hyperdb.Multilink):
            return None, files
        if not props['messages'].classname == 'msg':
            return None, files
        if not (self.form.has_key('nosy') or note):
            return None, files

        # handle the note
        if '\n' in note:
            summary = re.split(r'\n\r?', note)[0]
        else:
            summary = note
        m = ['%s\n'%note]

        # handle the messageid
        # TODO: handle inreplyto
        messageid = "<%s.%s.%s@%s>"%(time.time(), random.random(),
            self.classname, self.instance.config.MAIL_DOMAIN)

        # now create the message, attaching the files
        content = '\n'.join(m)
        message_id = self.db.msg.create(author=self.userid,
            recipients=[], date=date.Date('.'), summary=summary,
            content=content, files=files, messageid=messageid)

        # update the messages property
        return message_id, files

    def _post_editnode(self, nid):
        '''Do the linking part of the node creation.

           If a form element has :link or :multilink appended to it, its
           value specifies a node designator and the property on that node
           to add _this_ node to as a link or multilink.

           This is typically used on, eg. the file upload page to indicated
           which issue to link the file to.

           TODO: I suspect that this and newfile will go away now that
           there's the ability to upload a file using the issue :file form
           element!
        '''
        cn = self.classname
        cl = self.db.classes[cn]
        # link if necessary
        keys = self.form.keys()
        for key in keys:
            if key == ':multilink':
                value = self.form[key].value
                if type(value) != type([]): value = [value]
                for value in value:
                    designator, property = value.split(':')
                    link, nodeid = hyperdb.splitDesignator(designator)
                    link = self.db.classes[link]
                    # take a dupe of the list so we're not changing the cache
                    value = link.get(nodeid, property)[:]
                    value.append(nid)
                    link.set(nodeid, **{property: value})
            elif key == ':link':
                value = self.form[key].value
                if type(value) != type([]): value = [value]
                for value in value:
                    designator, property = value.split(':')
                    link, nodeid = hyperdb.splitDesignator(designator)
                    link = self.db.classes[link]
                    link.set(nodeid, **{property: nid})

def fixNewlines(text):
    ''' Homogenise line endings.

        Different web clients send different line ending values, but
        other systems (eg. email) don't necessarily handle those line
        endings. Our solution is to convert all line endings to LF.
    '''
    text = text.replace('\r\n', '\n')
    return text.replace('\r', '\n')


def parsePropsFromForm(db, cl, form, nodeid=0, num_re=re.compile('^\d+$')):
    ''' Pull properties for the given class out of the form.

        If a ":required" parameter is supplied, then the names property values
        must be supplied or a ValueError will be raised.

        Other special form values:
         :remove:<propname>=id(s)
          The ids will be removed from the multilink property.
         :add:<propname>=id(s)
          The ids will be added to the multilink property.
    '''
    required = []
    if form.has_key(':required'):
        value = form[':required']
        if isinstance(value, type([])):
            required = [i.value.strip() for i in value]
        else:
            required = [i.strip() for i in value.value.split(',')]

    props = {}
    keys = form.keys()
    properties = cl.getprops()
    for key in keys:
        # see if we're performing a special multilink action
        mlaction = 'set'
        if key.startswith(':remove:'):
            propname = key[8:]
            mlaction = 'remove'
        elif key.startswith(':add:'):
            propname = key[5:]
            mlaction = 'add'
        else:
            propname = key

        # does the property exist?
        if not properties.has_key(propname):
            if mlaction != 'set':
                raise ValueError, 'You have submitted a %s action for'\
                    ' the property "%s" which doesn\'t exist'%(mlaction,
                    propname)
            continue
        proptype = properties[propname]

        # Get the form value. This value may be a MiniFieldStorage or a list
        # of MiniFieldStorages.
        value = form[key]

        # handle unpacking of the MiniFieldStorage / list form value
        if isinstance(proptype, hyperdb.Multilink):
            # multiple values are OK
            if isinstance(value, type([])):
                # it's a list of MiniFieldStorages
                value = [i.value.strip() for i in value]
            else:
                # it's a MiniFieldStorage, but may be a comma-separated list
                # of values
                value = [i.strip() for i in value.value.split(',')]

            # filter out the empty bits
            value = filter(None, value)
        else:
            # multiple values are not OK
            if isinstance(value, type([])):
                raise ValueError, 'You have submitted more than one value'\
                    ' for the %s property'%propname
            # we've got a MiniFieldStorage, so pull out the value and strip
            # surrounding whitespace
            value = value.value.strip()

        if isinstance(proptype, hyperdb.String):
            # fix the CRLF/CR -> LF stuff
            value = fixNewlines(value)
            if not value:
                value = None
        elif isinstance(proptype, hyperdb.Password):
            if not value:
                # ignore empty password values
                continue
            if not form.has_key('%s:confirm'%propname):
                raise ValueError, 'Password and confirmation text do not match'
            confirm = form['%s:confirm'%propname]
            if isinstance(confirm, type([])):
                raise ValueError, 'You have submitted more than one value'\
                    ' for the %s property'%propname
            if value != confirm.value:
                raise ValueError, 'Password and confirmation text do not match'
            value = password.Password(value)
        elif isinstance(proptype, hyperdb.Date):
            if value:
                value = date.Date(value)
            else:
                value = None
        elif isinstance(proptype, hyperdb.Interval):
            if value:
                value = date.Interval(value)
            else:
                value = None
        elif isinstance(proptype, hyperdb.Link):
            # see if it's the "no selection" choice
            if value == '-1' or not value:
                # if we're creating, just don't include this property
                if not nodeid:
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
                elif nodeid:
                    existing = cl.get(nodeid, propname, [])
                else:
                    existing = []

                # now either remove or add
                if mlaction == 'remove':
                    # remove - handle situation where the id isn't in the list
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

        elif isinstance(proptype, hyperdb.Boolean):
            value = value.lower() in ('yes', 'true', 'on', '1')
        elif isinstance(proptype, hyperdb.Number):
            value = float(value)

        # register this as received if required?
        if propname in required and value is not None:
            required.remove(propname)

        # get the old value
        if nodeid:
            try:
                existing = cl.get(nodeid, propname)
            except KeyError:
                # this might be a new property for which there is no existing
                # value
                if not properties.has_key(propname):
                    raise

            # existing may be None, which won't equate to empty strings
            if not existing and not value:
                continue

            # existing will come out unsorted in some cases
            if isinstance(proptype, hyperdb.Multilink):
                existing.sort()

            # if changed, set it
            if value != existing:
                props[propname] = value
        else:
            # don't bother setting empty/unset values
            if not value:
                continue
            props[propname] = value

    # see if all the required properties have been supplied
    if required:
        if len(required) > 1:
            p = 'properties'
        else:
            p = 'property'
        raise ValueError, 'Required %s %s not supplied'%(p, ', '.join(required))

    return props
