# $Id: client.py,v 1.12 2002-09-05 01:27:42 richard Exp $

__doc__ = """
WWW request handler (also used in the stand-alone server).
"""

import os, os.path, cgi, StringIO, urlparse, re, traceback, mimetypes, urllib
import binascii, Cookie, time, random

from roundup import roundupdb, date, hyperdb, password
from roundup.i18n import _

from roundup.cgi.templating import getTemplate, HTMLRequest
from roundup.cgi import cgitb

from PageTemplates import PageTemplate

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
    '''
    A note about login
    ------------------

    If the user has no login cookie, then they are anonymous. There
    are two levels of anonymous use. If there is no 'anonymous' user, there
    is no login at all and the database is opened in read-only mode. If the
    'anonymous' user exists, the user is logged in using that user (though
    there is no cookie). This allows them to modify the database, and all
    modifications are attributed to the 'anonymous' user.

    Once a user logs in, they are assigned a session. The Client instance
    keeps the nodeid of the session as the "session" attribute.

    Client attributes:
        "url" is the current url path
        "path" is the PATH_INFO inside the instance
        "base" is the base URL for the instance
    '''

    def __init__(self, instance, request, env, form=None):
        hyperdb.traceMark()
        self.instance = instance
        self.request = request
        self.env = env

        self.path = env['PATH_INFO']
        self.split_path = self.path.split('/')
        self.instance_path_name = env['INSTANCE_NAME']

        # this is the base URL for this instance
        url = self.env['SCRIPT_NAME'] + '/' + self.instance_path_name
        self.base = urlparse.urlunparse(('http', env['HTTP_HOST'], url,
            None, None, None))

        # request.path is the full request path
        x, x, path, x, x, x = urlparse.urlparse(request.path)
        self.url = urlparse.urlunparse(('http', env['HTTP_HOST'], path,
            None, None, None))

        if form is None:
            self.form = cgi.FieldStorage(environ=env)
        else:
            self.form = form
        self.headers_done = 0
        try:
            self.debug = int(env.get("ROUNDUP_DEBUG", 0))
        except ValueError:
            # someone gave us a non-int debug level, turn it off
            self.debug = 0

    def main(self):
        ''' Wrap the request and handle unauthorised requests
        '''
        self.content_action = None
        self.ok_message = []
        self.error_message = []
        try:
            # make sure we're identified (even anonymously)
            self.determine_user()
            # figure out the context and desired content template
            self.determine_context()
            # possibly handle a form submit action (may change self.message,
            # self.classname and self.template)
            self.handle_action()
            # now render the page
            if self.form.has_key(':contentonly'):
                # just the content
                self.write(self.content())
            else:
                # render the content inside the page template
                self.write(self.renderTemplate('page', '',
                    ok_message=self.ok_message,
                    error_message=self.error_message))
        except Redirect, url:
            # let's redirect - if the url isn't None, then we need to do
            # the headers, otherwise the headers have been set before the
            # exception was raised
            if url:
                self.header({'Location': url}, response=302)
        except SendFile, designator:
            self.serve_file(designator)
        except SendStaticFile, file:
            self.serve_static_file(str(file))
        except Unauthorised, message:
            self.write(self.renderTemplate('page', '', error_message=message))
        except:
            # everything else
            self.write(cgitb.html())

    def determine_user(self):
        ''' Determine who the user is
        '''
        # determine the uid to use
        self.opendb('admin')

        # make sure we have the session Class
        sessions = self.db.sessions

        # age sessions, remove when they haven't been used for a week
        # TODO: this shouldn't be done every access
        week = 60*60*24*7
        now = time.time()
        for sessid in sessions.list():
            interval = now - sessions.get(sessid, 'last_use')
            if interval > week:
                sessions.destroy(sessid)

        # look up the user session cookie
        cookie = Cookie.Cookie(self.env.get('HTTP_COOKIE', ''))
        user = 'anonymous'

        # bump the "revision" of the cookie since the format changed
        if (cookie.has_key('roundup_user_2') and
                cookie['roundup_user_2'].value != 'deleted'):

            # get the session key from the cookie
            self.session = cookie['roundup_user_2'].value
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
        ''' Determine the context of this page:

             home              (default if no url is given)
             classname
             designator        (classname and nodeid)

            The desired template to be rendered is also determined There
            are two exceptional contexts:

             _file            - serve up a static file
             path len > 1     - serve up a FileClass content
                                (the additional path gives the browser a
                                 nicer filename to save as)

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
        path = self.split_path
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

        # see if we got a designator
        m = dre.match(self.classname)
        if m:
            self.classname = m.group(1)
            self.nodeid = m.group(2)
            # with a designator, we default to item view
            self.template = 'item'
        else:
            # with only a class, we default to index view
            self.template = 'index'

        # see if we have a template override
        if self.form.has_key(':template'):
            self.template = self.form[':template'].value


        # see if we were passed in a message
        if self.form.has_key(':ok_message'):
            self.ok_message.append(self.form[':ok_message'].value)
        if self.form.has_key(':error_message'):
            self.error_message.append(self.form[':error_message'].value)

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
        self.header({'Content-Type': file.get(nodeid, 'type')})
        self.write(file.get(nodeid, 'content'))

    def serve_static_file(self, file):
        # we just want to serve up the file named
        mt = mimetypes.guess_type(str(file))[0]
        self.header({'Content-Type': mt})
        self.write(open(os.path.join(self.instance.TEMPLATES, file)).read())

    def renderTemplate(self, name, extension, **kwargs):
        ''' Return a PageTemplate for the named page
        '''
        pt = getTemplate(self.instance.TEMPLATES, name, extension)
        # XXX handle PT rendering errors here more nicely
        try:
            # let the template render figure stuff out
            return pt.render(self, None, None, **kwargs)
        except PageTemplate.PTRuntimeError, message:
            return '<strong>%s</strong><ol>%s</ol>'%(message,
                '<li>'.join(pt._v_errors))
        except:
            # everything else
            return cgitb.html()

    def content(self):
        ''' Callback used by the page template to render the content of 
            the page.

            If we don't have a specific class to display, that is none was
            determined in determine_context(), then we display a "home"
            template.
        '''
        # now render the page content using the template we determined in
        # determine_context
        if self.classname is None:
            name = 'home'
        else:
            name = self.classname
        return self.renderTemplate(self.classname, self.template)

    # these are the actions that are available
    actions = {
        'edit':     'editItemAction',
        'editCSV':  'editCSVAction',
        'new':      'newItemAction',
        'register': 'registerAction',
        'login':    'login_action',
        'logout':   'logout_action',
        'search':   'searchAction',
    }
    def handle_action(self):
        ''' Determine whether there should be an _action called.

            The action is defined by the form variable :action which
            identifies the method on this object to call. The four basic
            actions are defined in the "actions" dictionary on this class:
             "edit"      -> self.editItemAction
             "new"       -> self.newItemAction
             "register"  -> self.registerAction
             "login"     -> self.login_action
             "logout"    -> self.logout_action
             "search"    -> self.searchAction

        '''
        if not self.form.has_key(':action'):
            return None
        try:
            # get the action, validate it
            action = self.form[':action'].value
            if not self.actions.has_key(action):
                raise ValueError, 'No such action "%s"'%action

            # call the mapped action
            getattr(self, self.actions[action])()
        except Redirect:
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

    def header(self, headers=None, response=200):
        '''Put up the appropriate header.
        '''
        if headers is None:
            headers = {'Content-Type':'text/html'}
        if not headers.has_key('Content-Type'):
            headers['Content-Type'] = 'text/html'
        self.request.send_response(response)
        for entry in headers.items():
            self.request.send_header(*entry)
        self.request.end_headers()
        self.headers_done = 1
        if self.debug:
            self.headers_sent = headers

    def set_cookie(self, user, password):
        # TODO generate a much, much stronger session key ;)
        self.session = binascii.b2a_base64(repr(time.time())).strip()

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
        path = '/'.join((self.env['SCRIPT_NAME'], self.env['INSTANCE_NAME'],
            ''))
        self.header({'Set-Cookie': 'roundup_user_2=%s; expires=%s; Path=%s;'%(
            self.session, expire, path)})

    def make_user_anonymous(self):
        ''' Make us anonymous

            This method used to handle non-existence of the 'anonymous'
            user, but that user is mandatory now.
        '''
        self.userid = self.db.user.lookup('anonymous')
        self.user = 'anonymous'

    def logout(self):
        ''' Make us really anonymous - nuke the cookie too
        '''
        self.make_user_anonymous()

        # construct the logout cookie
        now = Cookie._getdate()
        path = '/'.join((self.env['SCRIPT_NAME'], self.env['INSTANCE_NAME'],
            ''))
        self.header({'Set-Cookie':
            'roundup_user_2=deleted; Max-Age=0; expires=%s; Path=%s;'%(now,
            path)})
        self.login()

    def opendb(self, user):
        ''' Open the database.
        '''
        # open the db if the user has changed
        if not hasattr(self, 'db') or user != self.db.journaltag:
            self.db = self.instance.open(user)

    #
    # Actions
    #
    def login_action(self):
        ''' Attempt to log a user in and set the cookie
        '''
        # we need the username at a minimum
        if not self.form.has_key('__login_name'):
            self.error_message.append(_('Username required'))
            return

        self.user = self.form['__login_name'].value
        # re-open the database for real, using the user
        self.opendb(self.user)
        if self.form.has_key('__login_password'):
            password = self.form['__login_password'].value
        else:
            password = ''
        # make sure the user exists
        try:
            self.userid = self.db.user.lookup(self.user)
        except KeyError:
            name = self.user
            self.make_user_anonymous()
            self.error_message.append(_('No such user "%(name)s"')%locals())
            return

        # and that the password is correct
        pw = self.db.user.get(self.userid, 'password')
        if password != pw:
            self.make_user_anonymous()
            self.error_message.append(_('Incorrect password'))
            return

        # set the session cookie
        self.set_cookie(self.user, password)

    def logout_action(self):
        ''' Make us really anonymous - nuke the cookie too
        '''
        # log us out
        self.make_user_anonymous()

        # construct the logout cookie
        now = Cookie._getdate()
        path = '/'.join((self.env['SCRIPT_NAME'], self.env['INSTANCE_NAME'],
            ''))
        self.header(headers={'Set-Cookie':
          'roundup_user_2=deleted; Max-Age=0; expires=%s; Path=%s;'%(now, path)})

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
            props['roles'] = self.instance.NEW_WEB_USER_ROLES
            self.userid = cl.create(**props)
            self.db.commit()
        except ValueError, message:
            self.error_message.append(message)

        # log the new user in
        self.user = cl.get(self.userid, 'username')
        # re-open the database for real, using the user
        self.opendb(self.user)
        password = self.db.user.get(self.userid, 'password')
        self.set_cookie(self.user, password)

        # nice message
        self.ok_message.append(_('You are now registered, welcome!'))

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
            __note
             Create a message and attach it to the current node's
             "messages" property.
            __file
             Create a file and attach it to the current node's
             "files" property. Attach the file to the message created from
             the __note if it's supplied.
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
        except (ValueError, KeyError), message:
            self.error_message.append(_('Error: ') + str(message))
            return

        # commit now that all the tricky stuff is done
        self.db.commit()

        # and some nice feedback for the user
        if props:
            message = _('%(changes)s edited ok')%{'changes':
                ', '.join(props.keys())}
        elif self.form.has_key('__note') and self.form['__note'].value:
            message = _('note added')
        elif (self.form.has_key('__file') and self.form['__file'].filename):
            message = _('file added')
        else:
            message = _('nothing changed')

        # redirect to the item's edit page
        raise Redirect, '%s/%s%s?:ok_message=%s'%(self.base, self.classname,
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

            This follows the same form as the editItemAction
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

            # handle linked nodes 
            self._post_editnode(nid)

            # commit now that all the tricky stuff is done
            self.db.commit()

            # render the newly created item
            self.nodeid = nid

            # and some nice feedback for the user
            message = _('%(classname)s created ok')%self.__dict__ + xtra
        except (ValueError, KeyError), message:
            self.error_message.append(_('Error: ') + str(message))
            return
        except:
            # oops
            self.db.rollback()
            s = StringIO.StringIO()
            traceback.print_exc(None, s)
            self.error_message.append('<pre>%s</pre>'%cgi.escape(s.getvalue()))
            return

        # redirect to the new item's page
        raise Redirect, '%s/%s%s?:ok_message=%s'%(self.base, self.classname,
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
        props = self.db.classes[self.classname].getprops()
        for key in self.form.keys():
            if not props.has_key(key): continue
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

    def XXXremove_action(self,  dre=re.compile(r'([^\d]+)(\d+)')):
        # XXX I believe this could be handled by a regular edit action that
        # just sets the multilink...
        # XXX handle this !
        target = self.index_arg(':target')[0]
        m = dre.match(target)
        if m:
            classname = m.group(1)
            nodeid = m.group(2)
            cl = self.db.getclass(classname)
            cl.retire(nodeid)
            # now take care of the reference
            parentref =  self.index_arg(':multilink')[0]
            parent, prop = parentref.split(':')
            m = dre.match(parent)
            if m:
                self.classname = m.group(1)
                self.nodeid = m.group(2)
                cl = self.db.getclass(self.classname)
                value = cl.get(self.nodeid, prop)
                value.remove(nodeid)
                cl.set(self.nodeid, **{prop:value})
                func = getattr(self, 'show%s'%self.classname)
                return func()
            else:
                raise NotFound, parent
        else:
            raise NotFound, target

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
        if self.form.has_key('__file'):
            file = self.form['__file']
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
        if self.form.has_key('__note'):
            note = self.form['__note'].value.strip()
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
            self.classname, self.instance.MAIL_DOMAIN)

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
           there's the ability to upload a file using the issue __file form
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


def parsePropsFromForm(db, cl, form, nodeid=0, num_re=re.compile('^\d+$')):
    '''Pull properties for the given class out of the form.
    '''
    props = {}
    keys = form.keys()
    for key in keys:
        if not cl.properties.has_key(key):
            continue
        proptype = cl.properties[key]
        if isinstance(proptype, hyperdb.String):
            value = form[key].value.strip()
        elif isinstance(proptype, hyperdb.Password):
            value = form[key].value.strip()
            if not value:
                # ignore empty password values
                continue
            value = password.Password(value)
        elif isinstance(proptype, hyperdb.Date):
            value = form[key].value.strip()
            if value:
                value = date.Date(form[key].value.strip())
            else:
                value = None
        elif isinstance(proptype, hyperdb.Interval):
            value = form[key].value.strip()
            if value:
                value = date.Interval(form[key].value.strip())
            else:
                value = None
        elif isinstance(proptype, hyperdb.Link):
            value = form[key].value.strip()
            # see if it's the "no selection" choice
            if value == '-1':
                value = None
            else:
                # handle key values
                link = cl.properties[key].classname
                if not num_re.match(value):
                    try:
                        value = db.classes[link].lookup(value)
                    except KeyError:
                        raise ValueError, _('property "%(propname)s": '
                            '%(value)s not a %(classname)s')%{'propname':key, 
                            'value': value, 'classname': link}
        elif isinstance(proptype, hyperdb.Multilink):
            value = form[key]
            if not isinstance(value, type([])):
                value = [i.strip() for i in value.value.split(',')]
            else:
                value = [i.value.strip() for i in value]
            link = cl.properties[key].classname
            l = []
            for entry in map(str, value):
                if entry == '': continue
                if not num_re.match(entry):
                    try:
                        entry = db.classes[link].lookup(entry)
                    except KeyError:
                        raise ValueError, _('property "%(propname)s": '
                            '"%(value)s" not an entry of %(classname)s')%{
                            'propname':key, 'value': entry, 'classname': link}
                l.append(entry)
            l.sort()
            value = l
        elif isinstance(proptype, hyperdb.Boolean):
            value = form[key].value.strip()
            props[key] = value = value.lower() in ('yes', 'true', 'on', '1')
        elif isinstance(proptype, hyperdb.Number):
            value = form[key].value.strip()
            props[key] = value = int(value)

        # get the old value
        if nodeid:
            try:
                existing = cl.get(nodeid, key)
            except KeyError:
                # this might be a new property for which there is no existing
                # value
                if not cl.properties.has_key(key): raise

            # if changed, set it
            if value != existing:
                props[key] = value
        else:
            props[key] = value
    return props


