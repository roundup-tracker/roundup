# $Id: client.py,v 1.88 2003-02-17 01:04:31 richard Exp $

__doc__ = """
WWW request handler (also used in the stand-alone server).
"""

import os, os.path, cgi, StringIO, urlparse, re, traceback, mimetypes, urllib
import binascii, Cookie, time, random

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

    # specials for parsePropsFromForm
    FV_REQUIRED = re.compile(r'[@:]required')
    FV_ADD = re.compile(r'([@:])add\1')
    FV_REMOVE = re.compile(r'([@:])remove\1')
    FV_CONFIRM = re.compile(r'.+[@:]confirm')
    FV_LINK = re.compile(r'([@:])link\1(.+)')

    # deprecated
    FV_NOTE = re.compile(r'[@:]note')
    FV_FILE = re.compile(r'[@:]file')

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
            # make sure we're identified (even anonymously)
            self.determine_user()
            # figure out the context and desired content template
            self.determine_context()
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
            self.serve_static_file(str(file))
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

    def clean_sessions(self):
        '''age sessions, remove when they haven't been used for a week.
        Do it only once an hour'''
        sessions = self.db.sessions
        last_clean = sessions.get('last_clean', 'last_use') or 0

        week = 60*60*24*7
        hour = 60*60
        now = time.time()
        if now - last_clean > hour:
            # remove age sessions
            for sessid in sessions.list():
                interval = now - sessions.get(sessid, 'last_use')
                if interval > week:
                    sessions.destroy(sessid)
            sessions.set('last_clean', last_use=time.time())

    def determine_user(self):
        ''' Determine who the user is
        '''
        # determine the uid to use
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
            elif self.FV_ERROR_MESSAGE.match(key):
                error_message = self.form[key].value

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
        file = self.db.file
        self.additional_headers['Content-Type'] = file.get(nodeid, 'type')
        self.write(file.get(nodeid, 'content'))

    def serve_static_file(self, file):
        # we just want to serve up the file named
        mt = mimetypes.guess_type(str(file))[0]
        self.additional_headers['Content-Type'] = mt
        self.write(open(os.path.join(self.instance.config.TEMPLATES,
            file)).read())

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
        ('show',     'showAction'),
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
            props = self.parsePropsFromForm()
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
            props['roles'] = self.instance.config.NEW_WEB_USER_ROLES
            self.userid = cl.create(**props['user'])
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
        raise Redirect, '%s%s%s?+ok_message=%s'%(
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

           See parsePropsFromForm and _editnodes for special variables
        '''
        # parse the props from the form
        if 1:
#        try:
            props, links = self.parsePropsFromForm()
#        except (ValueError, KeyError), message:
#            self.error_message.append(_('Error: ') + str(message))
#            return

        # handle the props
        if 1:
#        try:
            message = self._editnodes(props, links)
#        except (ValueError, KeyError, IndexError), message:
#            self.error_message.append(_('Error: ') + str(message))
#            return

        # commit now that all the tricky stuff is done
        self.db.commit()

        # redirect to the item's edit page
        raise Redirect, '%s%s%s?@ok_message=%s'%(self.base, self.classname,
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
        # parse the props from the form
# XXX reinstate exception handling
#        try:
        if 1:
            props, links = self.parsePropsFromForm()
#        except (ValueError, KeyError), message:
#            self.error_message.append(_('Error: ') + str(message))
#            return

        # handle the props - edit or create
# XXX reinstate exception handling
#        try:
        if 1:
            # create the context here
            cn = self.classname
            nid = self._createnode(cn, props[(cn, None)])
            del props[(cn, None)]

            extra = self._editnodes(props, links, {(cn, None): nid})
            if extra:
                extra = '<br>' + extra

            # now do the rest
            messages = '%s %s created'%(cn, nid) + extra
#        except (ValueError, KeyError, IndexError), message:
#            # these errors might just be indicative of user dumbness
#            self.error_message.append(_('Error: ') + str(message))
#            return

        # commit now that all the tricky stuff is done
        self.db.commit()

        # redirect to the new item's page
        raise Redirect, '%s%s%s?@ok_message=%s'%(self.base, self.classname,
            nid, urllib.quote(messages))

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

            # confirm correct weight
            if len(idlessprops) != len(values):
                self.error_message.append(
                    _('Not enough values on line %(line)s')%{'line':line})
                return

            # extract the new values
            d = {}
            for name, value in zip(idlessprops, values):
                value = value.strip()
                # only add the property if it has a value
                if value:
                    # if it's a multilink, split it
                    if isinstance(cl.properties[name], hyperdb.Multilink):
                        value = value.split(':')
                    d[name] = value

            # perform the edit
            if cl.hasnode(nodeid):
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
# XXX migrate to new : @ + 
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


    def showAction(self):
        ''' Show a node
        '''
# XXX allow : @ +
        t = self.form[':type'].value
        n = self.form[':number'].value
        url = '%s%s%s'%(self.db.config.TRACKER_WEB, t, n)
        raise Redirect, url


    #
    #  Utility methods for editing
    #
    def _editnodes(self, all_props, all_links, newids=None):
        ''' Use the props in all_props to perform edit and creation, then
            use the link specs in all_links to do linking.
        '''
        m = []
        if newids is None:
            newids = {}
        for (cn, nodeid), props in all_props.items():
            if int(nodeid) > 0:
                # make changes to the node
                props = self._changenode(cn, nodeid, props)

                # and some nice feedback for the user
                if props:
                    info = ', '.join(props.keys())
                    m.append('%s %s %s edited ok'%(cn, nodeid, info))
                else:
                    m.append('%s %s - nothing changed'%(cn, nodeid))
            elif props:
                # make a new node
                newid = self._createnode(cn, props)
                newids[(cn, nodeid)] = newid
                nodeid = newid

                # and some nice feedback for the user
                m.append('%s %s created'%(cn, newid))

        # handle linked nodes
        keys = self.form.keys()
        for cn, nodeid, propname, value in all_links:
            cl = self.db.classes[cn]
            property = cl.getprops()[propname]
            if nodeid is None or nodeid.startswith('-'):
                if not newids.has_key((cn, nodeid)):
                    continue
                nodeid = newids[(cn, nodeid)]

            # map the desired classnames to their actual created ids
            for link in value:
                if not newids.has_key(link):
                    continue
                linkid = newids[link]
                if isinstance(property, hyperdb.Multilink):
                    # take a dupe of the list so we're not changing the cache
                    existing = cl.get(nodeid, propname)[:]
                    existing.append(linkid)
                    cl.set(nodeid, **{propname: existing})
                elif isinstance(property, hyperdb.Link):
                    # make the Link set
                    cl.set(nodeid, **{propname: linkid})
                else:
                    raise ValueError, '%s %s is not a link or multilink '\
                        'property'%(cn, propname)
                m.append('%s %s linked to <a href="%s%s">%s %s</a>'%(
                    link[0], linkid, cn, nodeid, cn, nodeid))

        return '<br>'.join(m)

    def _changenode(self, cn, nodeid, props):
        ''' change the node based on the contents of the form
        '''
        # check for permission
        if not self.editItemPermission(props):
            raise PermissionError, 'You do not have permission to edit %s'%cn

        # make the changes
        cl = self.db.classes[cn]
        return cl.set(nodeid, **props)

    def _createnode(self, cn, props):
        ''' create a node based on the contents of the form
        '''
        # check for permission
        if not self.newItemPermission(props):
            raise PermissionError, 'You do not have permission to create %s'%cn

        # create the node and return its id
        cl = self.db.classes[cn]
        return cl.create(**props)

    def parsePropsFromForm(self, num_re=re.compile('^\d+$')):
        ''' Pull properties for the given class out of the form.

            In the following, <bracketed> values are variable, ":" may be
            one of ":" or "@", and other text "required" is fixed.

            Properties are specified as form variables
             <designator>:<propname>

            where the propery belongs to the context class or item if the
            designator is not specified. The designator may specify a
            negative item id value (ie. "issue-1") and a new item of the
            specified class will be created for each negative id found.

            If a "<designator>:required" parameter is supplied,
            then the named property values must be supplied or a
            ValueError will be raised.

            Other special form values:
             [classname|designator]:remove:<propname>=id(s)
              The ids will be removed from the multilink property.
             [classname|designator]:add:<propname>=id(s)
              The ids will be added to the multilink property.

             [classname|designator]:link:<propname>=<classname>
              Used to add a link to new items created during edit.
              These are collected up and returned in all_links. This will
              result in an additional linking operation (either Link set or
              Multilink append) after the edit/create is done using
              all_props in _editnodes. The <propname> on
              [classname|designator] will be set/appended the id of the
              newly created item of class <classname>.

            Note: the colon may be either ":" or "@".

            Any of the form variables may be prefixed with a classname or
            designator.

            The return from this method is a dict of 
                (classname, id): properties
            ... this dict _always_ has an entry for the current context,
            even if it's empty (ie. a submission for an existing issue that
            doesn't result in any changes would return {('issue','123'): {}})
            The id may be None, which indicates that an item should be
            created.

            If a String property's form value is a file upload, then we
            try to set additional properties "filename" and "type" (if
            they are valid for the class).

            Two special form values are supported for backwards
            compatibility:
             :note - create a message (with content, author and date), link
                     to the context item
             :file - create a file, attach to the current item and any
                     message created by :note
        '''
        # some very useful variables
        db = self.db
        form = self.form

        if not hasattr(self, 'FV_ITEMSPEC'):
            # generate the regexp for detecting
            # <classname|designator>[@:+]property
            classes = '|'.join(db.classes.keys())
            self.FV_ITEMSPEC = re.compile(r'(%s)([-\d]+)[@:](.+)$'%classes)
            self.FV_DESIGNATOR = re.compile(r'(%s)([-\d]+)'%classes)

        # these indicate the default class / item
        default_cn = self.classname
        default_cl = self.db.classes[default_cn]
        default_nodeid = self.nodeid

        # we'll store info about the individual class/item edit in these
        all_required = {}       # one entry per class/item
        all_props = {}          # one entry per class/item
        all_propdef = {}        # note - only one entry per class
        all_links = []          # as many as are required

        # we should always return something, even empty, for the context
        all_props[(default_cn, default_nodeid)] = {}

        keys = form.keys()
        timezone = db.getUserTimezone()

        for key in keys:
            # see if this value modifies a different item to the default
            m = self.FV_ITEMSPEC.match(key)
            if m:
                # we got a designator
                cn = m.group(1)
                cl = self.db.classes[cn]
                nodeid = m.group(2)
                propname = m.group(3)
            elif key == ':note':
                # backwards compatibility: the special note field
                cn = 'msg'
                cl = self.db.classes[cn]
                nodeid = '-1'
                propname = 'content'
                all_links.append((default_cn, default_nodeid, 'messages',
                    [('msg', '-1')]))
            elif key == ':file':
                # backwards compatibility: the special file field
                cn = 'file'
                cl = self.db.classes[cn]
                nodeid = '-1'
                propname = 'content'
                all_links.append((default_cn, default_nodeid, 'files',
                    [('file', '-1')]))
                if self.form.has_key(':note'):
                    all_links.append(('msg', '-1', 'files', [('file', '-1')]))
            else:
                # default
                cn = default_cn
                cl = default_cl
                nodeid = default_nodeid
                propname = key

            # the thing this value relates to is...
            this = (cn, nodeid)

            # is this a link command?
            if self.FV_LINK.match(propname):
                value = []
                for entry in extractFormList(form[key]):
                    m = self.FV_DESIGNATOR.match(entry)
                    if not m:
                        raise ValueError, \
                            'link "%s" value "%s" not a designator'%(key, entry)
                    value.append((m.groups(1), m.groups(2)))
                all_links.append((cn, nodeid, propname[6:], value))

            # get more info about the class, and the current set of
            # form props for it
            if not all_propdef.has_key(cn):
                all_propdef[cn] = cl.getprops()
            propdef = all_propdef[cn]
            if not all_props.has_key(this):
                all_props[this] = {}
            props = all_props[this]

            # detect the special ":required" variable
            if self.FV_REQUIRED.match(key):
                all_required[this] = extractFormList(form[key])
                continue

            # get the required values list
            if not all_required.has_key(this):
                all_required[this] = []
            required = all_required[this]

            # see if we're performing a special multilink action
            mlaction = 'set'
            if self.FV_REMOVE.match(propname):
                propname = propname[8:]
                mlaction = 'remove'
            elif self.FV_ADD.match(propname):
                propname = propname[5:]
                mlaction = 'add'

            # does the property exist?
            if not propdef.has_key(propname):
                if mlaction != 'set':
                    raise ValueError, 'You have submitted a %s action for'\
                        ' the property "%s" which doesn\'t exist'%(mlaction,
                        propname)
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
            if key == ':note' and value:
                props['author'] = self.db.getuid()
                props['date'] = date.Date()

            # handle by type now
            if isinstance(proptype, hyperdb.Password):
                if not value:
                    # ignore empty password values
                    continue
                for key in keys:
                    if self.FV_CONFIRM.match(key):
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
                if isinstance(proptype, hyperdb.String):
                    if (hasattr(value, 'filename') and
                            value.filename is not None):
                        # skip if the upload is empty
                        if not value.filename:
                            continue
                        # this String is actually a _file_
                        # try to determine the file content-type
                        filename = value.filename.split('\\')[-1]
                        if propdef.has_key('name'):
                            props['name'] = filename
                        # use this info as the type/filename properties
                        if propdef.has_key('type'):
                            props['type'] = mimetypes.guess_type(filename)[0]
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

            # register this as received if required?
            if propname in required and value is not None:
                required.remove(propname)

        # see if all the required properties have been supplied
        s = []
        for thing, required in all_required.items():
            if not required:
                continue
            if len(required) > 1:
                p = 'properties'
            else:
                p = 'property'
            s.append('Required %s %s %s not supplied'%(thing[0], p,
                ', '.join(required)))
        if s:
            raise ValueError, '\n'.join(s)

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
         [MiniFieldStorage, MiniFieldStorage, ...]
         MiniFieldStorage('value,value,...')
         MiniFieldStorage('value')
    '''
    # multiple values are OK
    if isinstance(value, type([])):
        # it's a list of MiniFieldStorages
        value = [i.value.strip() for i in value]
    else:
        # it's a MiniFieldStorage, but may be a comma-separated list
        # of values
        value = [i.strip() for i in value.value.split(',')]

    # filter out the empty bits
    return filter(None, value)

