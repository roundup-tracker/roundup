import re, cgi, StringIO, urllib, Cookie, time, random

from roundup import hyperdb, token, date, password, rcsv
from roundup.i18n import _
from roundup.cgi import templating
from roundup.cgi.exceptions import Redirect, Unauthorised
from roundup.mailgw import uidFromAddress

__all__ = ['Action', 'ShowAction', 'RetireAction', 'SearchAction',
           'EditCSVAction', 'EditItemAction', 'PassResetAction',
           'ConfRegoAction', 'RegisterAction', 'LoginAction', 'LogoutAction',
           'NewItemAction']

# used by a couple of routines
chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'

class Action:    
    def __init__(self, client):
        self.client = client
        self.form = client.form
        self.db = client.db
        self.nodeid = client.nodeid
        self.template = client.template
        self.classname = client.classname
        self.userid = client.userid
        self.base = client.base
        self.user = client.user
        
    def execute(self):
        """Execute the action specified by this object."""
        self.permission()
        self.handle()

    name = ''
    permissionType = None
    def permission(self):
        """Check whether the user has permission to execute this action.

        True by default. If the permissionType attribute is a string containing
        a simple permission, check whether the user has that permission.
        Subclasses must also define the name attribute if they define
        permissionType.
        
        Despite having this permission, users may still be unauthorised to
        perform parts of actions. It is up to the subclasses to detect this.        
        """
        if (self.permissionType and
            not self.hasPermission(self.permissionType)):

            raise Unauthorised, _('You do not have permission to %s the %s class.' %
                                  (self.name, self.classname))

    def hasPermission(self, permission):
        """Check whether the user has 'permission' on the current class."""
        return self.db.security.hasPermission(permission, self.client.userid,
                                              self.client.classname)

class ShowAction(Action):
    def handle(self, typere=re.compile('[@:]type'),
               numre=re.compile('[@:]number')):
        """Show a node of a particular class/id."""
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

class RetireAction(Action):
    name = 'retire'
    permissionType = 'Edit'

    def handle(self):
        """Retire the context item."""        
        # if we want to view the index template now, then unset the nodeid
        # context info (a special-case for retire actions on the index page)
        nodeid = self.nodeid
        if self.template == 'index':
            self.client.nodeid = None

        # make sure we don't try to retire admin or anonymous
        if self.classname == 'user' and \
                self.db.user.get(nodeid, 'username') in ('admin', 'anonymous'):
            raise ValueError, _('You may not retire the admin or anonymous user')

        # do the retire
        self.db.getclass(self.classname).retire(nodeid)
        self.db.commit()

        self.client.ok_message.append(
            _('%(classname)s %(itemid)s has been retired')%{
                'classname': self.classname.capitalize(), 'itemid': nodeid})

class SearchAction(Action):
    name = 'search'
    permissionType = 'View'
    
    def handle(self, wcre=re.compile(r'[\s,]+')):
        """Mangle some of the form variables.

        Set the form ":filter" variable based on the values of the filter
        variables - if they're set to anything other than "dontcare" then add
        them to :filter.

        Handle the ":queryname" variable and save off the query to the user's
        query list.

        Split any String query values on whitespace and comma.

        """
        self.fakeFilterVars()
        queryname = self.getQueryName()        

        # handle saving the query params
        if queryname:
            # parse the environment and figure what the query _is_
            req = templating.HTMLRequest(self.client)

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

    def fakeFilterVars(self):
        """Add a faked :filter form variable for each filtering prop."""
        props = self.db.classes[self.classname].getprops()
        for key in self.form.keys():
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

    FV_QUERYNAME = re.compile(r'[@:]queryname')
    def getQueryName(self):
        for key in self.form.keys():
            if self.FV_QUERYNAME.match(key):
                return self.form[key].value.strip()
        return ''

class EditCSVAction(Action):
    name = 'edit'
    permissionType = 'Edit'
    
    def handle(self):
        """Performs an edit of all of a class' items in one go.

        The "rows" CGI var defines the CSV-formatted entries for the class. New
        nodes are identified by the ID 'X' (or any other non-existent ID) and
        removed lines are retired.

        """
        # get the CSV module
        if rcsv.error:
            self.client.error_message.append(_(rcsv.error))
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
                self.client.error_message.append(
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

        self.client.ok_message.append(_('Items edited OK'))
    
class _EditAction(Action):
    def isEditingSelf(self):
        """Check whether a user is editing his/her own details."""
        return (self.nodeid == self.userid
                and self.db.user.get(self.nodeid, 'username') != 'anonymous')
    
    def editItemPermission(self, props):
        """Determine whether the user has permission to edit this item.

        Base behaviour is to check the user can edit this class. If we're
        editing the "user" class, users are allowed to edit their own details.
        Unless it's the "roles" property, which requires the special Permission
        "Web Roles".
        """
        if self.classname == 'user':
            if props.has_key('roles') and not self.hasPermission('Web Roles'):
                raise Unauthorised, _("You do not have permission to edit user roles")
            if self.isEditingSelf():
                return 1
        if self.hasPermission('Edit'):
            return 1
        return 0

    def newItemPermission(self, props):
        """Determine whether the user has permission to create (edit) this item.

        Base behaviour is to check the user can edit this class. No additional
        property checks are made. Additionally, new user items may be created
        if the user has the "Web Registration" Permission.

        """
        if (self.classname == 'user' and self.hasPermission('Web Registration')
            or self.hasPermission('Edit')):
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
        """Change the node based on the contents of the form."""
        # check for permission
        if not self.editItemPermission(props):
            raise Unauthorised, 'You do not have permission to edit %s'%cn

        # make the changes
        cl = self.db.classes[cn]
        return cl.set(nodeid, **props)

    def _createnode(self, cn, props):
        """Create a node based on the contents of the form."""
        # check for permission
        if not self.newItemPermission(props):
            raise Unauthorised, 'You do not have permission to create %s'%cn

        # create the node and return its id
        cl = self.db.classes[cn]
        return cl.create(**props)

class EditItemAction(_EditAction):
    def lastUserActivity(self):
        if self.form.has_key(':lastactivity'):
            return date.Date(self.form[':lastactivity'].value)
        elif self.form.has_key('@lastactivity'):
            return date.Date(self.form['@lastactivity'].value)
        else:
            return None

    def lastNodeActivity(self):
        cl = getattr(self.client.db, self.classname)
        return cl.get(self.nodeid, 'activity')

    def detectCollision(self, userActivity, nodeActivity):
        # Result from lastUserActivity may be None. If it is, assume there's no
        # conflict, or at least not one we can detect.
        if userActivity:
            return userActivity < nodeActivity

    def handleCollision(self):
        self.client.template = 'collision'
    
    def handle(self):
        """Perform an edit of an item in the database.

        See parsePropsFromForm and _editnodes for special variables.
        
        """
        if self.detectCollision(self.lastUserActivity(), self.lastNodeActivity()):
            self.handleCollision()
            return

        props, links = self.client.parsePropsFromForm()

        # handle the props
        try:
            message = self._editnodes(props, links)
        except (ValueError, KeyError, IndexError), message:
            self.client.error_message.append(_('Apply Error: ') + str(message))
            return

        # commit now that all the tricky stuff is done
        self.db.commit()

        # redirect to the item's edit page
        # redirect to finish off
        url = self.base + self.classname
        # note that this action might have been called by an index page, so
        # we will want to include index-page args in this URL too
        if self.nodeid is not None:
            url += self.nodeid
        url += '?@ok_message=%s&@template=%s'%(urllib.quote(message),
            urllib.quote(self.template))
        if self.nodeid is None:
            req = templating.HTMLRequest(self)
            url += '&' + req.indexargs_href('', {})[1:]
        raise Redirect, url
    
class NewItemAction(_EditAction):
    def handle(self):
        ''' Add a new item to the database.

            This follows the same form as the EditItemAction, with the same
            special form values.
        '''
        # parse the props from the form
        try:
            props, links = self.client.parsePropsFromForm(create=True)
        except (ValueError, KeyError), message:
            self.client.error_message.append(_('Error: ') + str(message))
            return

        # handle the props - edit or create
        try:
            # when it hits the None element, it'll set self.nodeid
            messages = self._editnodes(props, links)

        except (ValueError, KeyError, IndexError), message:
            # these errors might just be indicative of user dumbness
            self.client.error_message.append(_('Error: ') + str(message))
            return

        # commit now that all the tricky stuff is done
        self.db.commit()

        # redirect to the new item's page
        raise Redirect, '%s%s%s?@ok_message=%s&@template=%s'%(self.base,
            self.classname, self.nodeid, urllib.quote(messages),
            urllib.quote(self.template))
        
class PassResetAction(Action):
    def handle(self):
        """Handle password reset requests.
    
        Presence of either "name" or "address" generates email. Presence of
        "otk" performs the reset.
    
        """
        if self.form.has_key('otk'):
            # pull the rego information out of the otk database
            otk = self.form['otk'].value
            uid = self.db.otks.get(otk, 'uid')
            if uid is None:
                self.client.error_message.append("""Invalid One Time Key!
(a Mozilla bug may cause this message to show up erroneously,
 please check your email)""")
                return

            # re-open the database as "admin"
            if self.user != 'admin':
                self.client.opendb('admin')
                self.db = self.client.db

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
                self.client.error_message.append(str(message))
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
            if not self.client.standard_message([address], subject, body):
                return

            self.client.ok_message.append('Password reset and email sent to %s' %
                                          address)
            return

        # no OTK, so now figure the user
        if self.form.has_key('username'):
            name = self.form['username'].value
            try:
                uid = self.db.user.lookup(name)
            except KeyError:
                self.client.error_message.append('Unknown username')
                return
            address = self.db.user.get(uid, 'address')
        elif self.form.has_key('address'):
            address = self.form['address'].value
            uid = uidFromAddress(self.db, ('', address), create=0)
            if not uid:
                self.client.error_message.append('Unknown email address')
                return
            name = self.db.user.get(uid, 'username')
        else:
            self.client.error_message.append('You need to specify a username '
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
        if not self.client.standard_message([address], subject, body):
            return

        self.client.ok_message.append('Email sent to %s'%address)

class ConfRegoAction(Action):
    def handle(self):
        """Grab the OTK, use it to load up the new user details."""
        try:
            # pull the rego information out of the otk database
            self.userid = self.db.confirm_registration(self.form['otk'].value)
        except (ValueError, KeyError), message:
            # XXX: we need to make the "default" page be able to display errors!
            self.client.error_message.append(str(message))
            return
        
        # log the new user in
        self.client.user = self.db.user.get(self.userid, 'username')
        # re-open the database for real, using the user
        self.client.opendb(self.client.user)
        self.db = client.db

        # if we have a session, update it
        if hasattr(self, 'session'):
            self.db.sessions.set(self.session, user=self.user,
                last_use=time.time())
        else:
            # new session cookie
            self.client.set_cookie(self.user)

        # nice message
        message = _('You are now registered, welcome!')

        # redirect to the user's page
        raise Redirect, '%suser%s?@ok_message=%s'%(self.base,
                                                   self.userid, urllib.quote(message))

class RegisterAction(Action):
    name = 'register'
    permissionType = 'Web Registration'
    
    def handle(self):
        """Attempt to create a new user based on the contents of the form
        and then set the cookie.

        Return 1 on successful login.
        """        
        props = self.client.parsePropsFromForm()[0][('user', None)]

        # registration isn't allowed to supply roles
        if props.has_key('roles'):
            raise Unauthorised, _("It is not permitted to supply roles at registration.")            

        try:
            self.db.user.lookup(props['username'])
            self.client.error_message.append('Error: A user with the username "%s" '
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
        tracker_email = self.db.config.TRACKER_EMAIL
        subject = 'Complete your registration to %s -- key %s' % (tracker_name,
                                                                  otk)
        body = """To complete your registration of the user "%(name)s" with
%(tracker)s, please do one of the following:

- send a reply to %(tracker_email)s and maintain the subject line as is (the
reply's additional "Re:" is ok),

- or visit the following URL:

%(url)s?@action=confrego&otk=%(otk)s
""" % {'name': props['username'], 'tracker': tracker_name, 'url': self.base,
        'otk': otk, 'tracker_email': tracker_email}
        if not self.client.standard_message([props['address']], subject, body,
        tracker_email):
            return

        # commit changes to the database
        self.db.commit()

        # redirect to the "you're almost there" page
        raise Redirect, '%suser?@template=rego_progress'%self.base

class LogoutAction(Action):
    def handle(self):
        """Make us really anonymous - nuke the cookie too."""
        # log us out
        self.client.make_user_anonymous()

        # construct the logout cookie
        now = Cookie._getdate()
        self.client.additional_headers['Set-Cookie'] = \
           '%s=deleted; Max-Age=0; expires=%s; Path=%s;'%(self.client.cookie_name,
            now, self.client.cookie_path)

        # Let the user know what's going on
        self.client.ok_message.append(_('You are logged out'))

class LoginAction(Action):
    def handle(self):
        """Attempt to log a user in.

        Sets up a session for the user which contains the login credentials.

        """
        # we need the username at a minimum
        if not self.form.has_key('__login_name'):
            self.client.error_message.append(_('Username required'))
            return

        # get the login info
        self.client.user = self.form['__login_name'].value
        if self.form.has_key('__login_password'):
            password = self.form['__login_password'].value
        else:
            password = ''

        # make sure the user exists
        try:
            self.client.userid = self.db.user.lookup(self.client.user)
        except KeyError:
            name = self.client.user
            self.client.error_message.append(_('No such user "%(name)s"')%locals())
            self.client.make_user_anonymous()
            return

        # verify the password
        if not self.verifyPassword(self.client.userid, password):
            self.client.make_user_anonymous()
            self.client.error_message.append(_('Incorrect password'))
            return

        # Determine whether the user has permission to log in.
        # Base behaviour is to check the user has "Web Access".
        if not self.hasPermission("Web Access"):
            self.client.make_user_anonymous()
            self.client.error_message.append(_("You do not have permission to login"))
            return

        # now we're OK, re-open the database for real, using the user
        self.client.opendb(self.client.user)

        # set the session cookie
        self.client.set_cookie(self.client.user)

    def verifyPassword(self, userid, password):
        ''' Verify the password that the user has supplied
        '''
        stored = self.db.user.get(self.client.userid, 'password')
        if password == stored:
            return 1
        if not password and not stored:
            return 1
        return 0
