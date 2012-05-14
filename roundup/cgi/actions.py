import re, cgi, time, random, csv, codecs

from roundup import hyperdb, token, date, password
from roundup.actions import Action as BaseAction
from roundup.i18n import _
import roundup.exceptions
from roundup.cgi import exceptions, templating
from roundup.mailgw import uidFromAddress
from roundup.anypy import io_, urllib_

__all__ = ['Action', 'ShowAction', 'RetireAction', 'SearchAction',
           'EditCSVAction', 'EditItemAction', 'PassResetAction',
           'ConfRegoAction', 'RegisterAction', 'LoginAction', 'LogoutAction',
           'NewItemAction', 'ExportCSVAction']

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
        self.context = templating.context(client)

    def handle(self):
        """Action handler procedure"""
        raise NotImplementedError

    def execute(self):
        """Execute the action specified by this object."""
        self.permission()
        return self.handle()

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
            info = {'action': self.name, 'classname': self.classname}
            raise exceptions.Unauthorised(self._(
                'You do not have permission to '
                '%(action)s the %(classname)s class.')%info)

    _marker = []
    def hasPermission(self, permission, classname=_marker, itemid=None, property=None):
        """Check whether the user has 'permission' on the current class."""
        if classname is self._marker:
            classname = self.client.classname
        return self.db.security.hasPermission(permission, self.client.userid,
            classname=classname, itemid=itemid, property=property)

    def gettext(self, msgid):
        """Return the localized translation of msgid"""
        return self.client.translator.gettext(msgid)

    _ = gettext

class ShowAction(Action):

    typere=re.compile('[@:]type')
    numre=re.compile('[@:]number')

    def handle(self):
        """Show a node of a particular class/id."""
        t = n = ''
        for key in self.form:
            if self.typere.match(key):
                t = self.form[key].value.strip()
            elif self.numre.match(key):
                n = self.form[key].value.strip()
        if not t:
            raise ValueError(self._('No type specified'))
        if not n:
            raise exceptions.SeriousError(self._('No ID entered'))
        try:
            int(n)
        except ValueError:
            d = {'input': n, 'classname': t}
            raise exceptions.SeriousError(self._(
                '"%(input)s" is not an ID (%(classname)s ID required)')%d)
        url = '%s%s%s'%(self.base, t, n)
        raise exceptions.Redirect(url)

class RetireAction(Action):
    name = 'retire'
    permissionType = 'Edit'

    def handle(self):
        """Retire the context item."""
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise roundup.exceptions.Reject(self._('Invalid request'))

        # if we want to view the index template now, then unset the itemid
        # context info (a special-case for retire actions on the index page)
        itemid = self.nodeid
        if self.template == 'index':
            self.client.nodeid = None

        # make sure we don't try to retire admin or anonymous
        if self.classname == 'user' and \
                self.db.user.get(itemid, 'username') in ('admin', 'anonymous'):
            raise ValueError(self._(
                'You may not retire the admin or anonymous user'))

        # check permission
        if not self.hasPermission('Retire', classname=self.classname,
                itemid=itemid):
            raise exceptions.Unauthorised(self._(
                'You do not have permission to retire %(class)s'
            ) % {'class': self.classname})

        # do the retire
        self.db.getclass(self.classname).retire(itemid)
        self.db.commit()

        self.client.ok_message.append(
            self._('%(classname)s %(itemid)s has been retired')%{
                'classname': self.classname.capitalize(), 'itemid': itemid})


class SearchAction(Action):
    name = 'search'
    permissionType = 'View'

    def handle(self):
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

        # editing existing query name?
        old_queryname = self.getFromForm('old-queryname')

        # handle saving the query params
        if queryname:
            # parse the environment and figure what the query _is_
            req = templating.HTMLRequest(self.client)

            url = self.getCurrentURL(req)

            key = self.db.query.getkey()
            if key:
                # edit the old way, only one query per name
                try:
                    qid = self.db.query.lookup(old_queryname)
                    if not self.hasPermission('Edit', 'query', itemid=qid):
                        raise exceptions.Unauthorised(self._(
                            "You do not have permission to edit queries"))
                    self.db.query.set(qid, klass=self.classname, url=url)
                except KeyError:
                    # create a query
                    if not self.hasPermission('Create', 'query'):
                        raise exceptions.Unauthorised(self._(
                            "You do not have permission to store queries"))
                    qid = self.db.query.create(name=queryname,
                        klass=self.classname, url=url)
            else:
                # edit the new way, query name not a key any more
                # see if we match an existing private query
                uid = self.db.getuid()
                qids = self.db.query.filter(None, {'name': old_queryname,
                        'private_for': uid})
                if not qids:
                    # ok, so there's not a private query for the current user
                    # - see if there's one created by them
                    qids = self.db.query.filter(None, {'name': old_queryname,
                        'creator': uid})

                if qids and old_queryname:
                    # edit query - make sure we get an exact match on the name
                    for qid in qids:
                        if old_queryname != self.db.query.get(qid, 'name'):
                            continue
                        if not self.hasPermission('Edit', 'query', itemid=qid):
                            raise exceptions.Unauthorised(self._(
                            "You do not have permission to edit queries"))
                        self.db.query.set(qid, klass=self.classname,
                            url=url, name=queryname)
                else:
                    # create a query
                    if not self.hasPermission('Create', 'query'):
                        raise exceptions.Unauthorised(self._(
                            "You do not have permission to store queries"))
                    qid = self.db.query.create(name=queryname,
                        klass=self.classname, url=url, private_for=uid)

            # and add it to the user's query multilink
            queries = self.db.user.get(self.userid, 'queries')
            if qid not in queries:
                queries.append(qid)
                self.db.user.set(self.userid, queries=queries)

            # commit the query change to the database
            self.db.commit()

    def fakeFilterVars(self):
        """Add a faked :filter form variable for each filtering prop."""
        cls = self.db.classes[self.classname]
        for key in self.form:
            prop = cls.get_transitive_prop(key)
            if not prop:
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
                if isinstance(prop, hyperdb.String):
                    v = self.form[key].value
                    l = token.token_split(v)
                    if len(l) != 1 or l[0] != v:
                        self.form.value.remove(self.form[key])
                        # replace the single value with the split list
                        for v in l:
                            self.form.value.append(cgi.MiniFieldStorage(key, v))

            self.form.value.append(cgi.MiniFieldStorage('@filter', key))

    def getCurrentURL(self, req):
        """Get current URL for storing as a query.

        Note: We are removing the first character from the current URL,
        because the leading '?' is not part of the query string.

        Implementation note:
        But maybe the template should be part of the stored query:
        template = self.getFromForm('template')
        if template:
            return req.indexargs_url('', {'@template' : template})[1:]
        """
        return req.indexargs_url('', {})[1:]

    def getFromForm(self, name):
        for key in ('@' + name, ':' + name):
            if key in self.form:
                return self.form[key].value.strip()
        return ''

    def getQueryName(self):
        return self.getFromForm('queryname')

class EditCSVAction(Action):
    name = 'edit'
    permissionType = 'Edit'

    def handle(self):
        """Performs an edit of all of a class' items in one go.

        The "rows" CGI var defines the CSV-formatted entries for the class. New
        nodes are identified by the ID 'X' (or any other non-existent ID) and
        removed lines are retired.
        """
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise roundup.exceptions.Reject(self._('Invalid request'))

        # figure the properties list for the class
        cl = self.db.classes[self.classname]
        props_without_id = list(cl.getprops(protected=0))

        # the incoming CSV data will always have the properties in colums
        # sorted and starting with the "id" column
        props_without_id.sort()
        props = ['id'] + props_without_id

        # do the edit
        rows = io_.BytesIO(self.form['rows'].value)
        reader = csv.reader(rows)
        found = {}
        line = 0
        for values in reader:
            line += 1
            if line == 1: continue
            # skip property names header
            if values == props:
                continue

            # extract the itemid
            itemid, values = values[0], values[1:]
            found[itemid] = 1

            # see if the node exists
            if itemid in ('x', 'X') or not cl.hasnode(itemid):
                exists = 0

                # check permission to create this item
                if not self.hasPermission('Create', classname=self.classname):
                    raise exceptions.Unauthorised(self._(
                        'You do not have permission to create %(class)s'
                    ) % {'class': self.classname})
            elif cl.hasnode(itemid) and cl.is_retired(itemid):
                # If a CSV line just mentions an id and the corresponding
                # item is retired, then the item is restored.
                cl.restore(itemid)
                continue
            else:
                exists = 1

            # confirm correct weight
            if len(props_without_id) != len(values):
                self.client.error_message.append(
                    self._('Not enough values on line %(line)s')%{'line':line})
                return

            # extract the new values
            d = {}
            for name, value in zip(props_without_id, values):
                # check permission to edit this property on this item
                if exists and not self.hasPermission('Edit', itemid=itemid,
                        classname=self.classname, property=name):
                    raise exceptions.Unauthorised(self._(
                        'You do not have permission to edit %(class)s'
                    ) % {'class': self.classname})

                prop = cl.properties[name]
                value = value.strip()
                # only add the property if it has a value
                if value:
                    # if it's a multilink, split it
                    if isinstance(prop, hyperdb.Multilink):
                        value = value.split(':')
                    elif isinstance(prop, hyperdb.Password):
                        value = password.Password(value, config=self.db.config)
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
                cl.set(itemid, **d)
            else:
                # new node
                found[cl.create(**d)] = 1

        # retire the removed entries
        for itemid in cl.list():
            if itemid not in found:
                # check permission to retire this item
                if not self.hasPermission('Retire', itemid=itemid,
                        classname=self.classname):
                    raise exceptions.Unauthorised(self._(
                        'You do not have permission to retire %(class)s'
                    ) % {'class': self.classname})
                cl.retire(itemid)

        # all OK
        self.db.commit()

        self.client.ok_message.append(self._('Items edited OK'))

class EditCommon(Action):
    '''Utility methods for editing.'''

    def _editnodes(self, all_props, all_links):
        ''' Use the props in all_props to perform edit and creation, then
            use the link specs in all_links to do linking.
        '''
        # figure dependencies and re-work links
        deps = {}
        links = {}
        for cn, nodeid, propname, vlist in all_links:
            numeric_id = int (nodeid or 0)
            if not (numeric_id > 0 or (cn, nodeid) in all_props):
                # link item to link to doesn't (and won't) exist
                continue

            for value in vlist:
                if value not in all_props:
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
            for needed in all_props:
                if needed in done:
                    continue
                tlist = deps.get(needed, [])
                for target in tlist:
                    if target not in done:
                        break
                else:
                    done[needed] = 1
                    order.append(needed)
                    change = 1
            if not change:
                raise ValueError('linking must not loop!')

        # now, edit / create
        m = []
        for needed in order:
            props = all_props[needed]
            cn, nodeid = needed
            if props:
                if nodeid is not None and int(nodeid) > 0:
                    # make changes to the node
                    props = self._changenode(cn, nodeid, props)

                    # and some nice feedback for the user
                    if props:
                        info = ', '.join(map(self._, props))
                        m.append(
                            self._('%(class)s %(id)s %(properties)s edited ok')
                            % {'class':cn, 'id':nodeid, 'properties':info})
                    else:
                        m.append(self._('%(class)s %(id)s - nothing changed')
                            % {'class':cn, 'id':nodeid})
                else:
                    assert props

                    # make a new node
                    newid = self._createnode(cn, props)
                    if nodeid is None:
                        self.nodeid = newid
                    nodeid = newid

                    # and some nice feedback for the user
                    m.append(self._('%(class)s %(id)s created')
                        % {'class':cn, 'id':newid})

            # fill in new ids in links
            if needed in links:
                for linkcn, linkid, linkprop in links[needed]:
                    props = all_props[(linkcn, linkid)]
                    cl = self.db.classes[linkcn]
                    propdef = cl.getprops()[linkprop]
                    if linkprop not in props:
                        if linkid is None or linkid.startswith('-'):
                            # linking to a new item
                            if isinstance(propdef, hyperdb.Multilink):
                                props[linkprop] = [nodeid]
                            else:
                                props[linkprop] = nodeid
                        else:
                            # linking to an existing item
                            if isinstance(propdef, hyperdb.Multilink):
                                existing = cl.get(linkid, linkprop)[:]
                                existing.append(nodeid)
                                props[linkprop] = existing
                            else:
                                props[linkprop] = nodeid

        return '\n'.join(m)

    def _changenode(self, cn, nodeid, props):
        """Change the node based on the contents of the form."""
        # check for permission
        if not self.editItemPermission(props, classname=cn, itemid=nodeid):
            raise exceptions.Unauthorised(self._(
                'You do not have permission to edit %(class)s'
            ) % {'class': cn})

        # make the changes
        cl = self.db.classes[cn]
        return cl.set(nodeid, **props)

    def _createnode(self, cn, props):
        """Create a node based on the contents of the form."""
        # check for permission
        if not self.newItemPermission(props, classname=cn):
            raise exceptions.Unauthorised(self._(
                'You do not have permission to create %(class)s'
            ) % {'class': cn})

        # create the node and return its id
        cl = self.db.classes[cn]
        return cl.create(**props)

    def isEditingSelf(self):
        """Check whether a user is editing his/her own details."""
        return (self.nodeid == self.userid
                and self.db.user.get(self.nodeid, 'username') != 'anonymous')

    _cn_marker = []
    def editItemPermission(self, props, classname=_cn_marker, itemid=None):
        """Determine whether the user has permission to edit this item."""
        if itemid is None:
            itemid = self.nodeid
        if classname is self._cn_marker:
            classname = self.classname
        # The user must have permission to edit each of the properties
        # being changed.
        for p in props:
            if not self.hasPermission('Edit', itemid=itemid,
                    classname=classname, property=p):
                return 0
        # Since the user has permission to edit all of the properties,
        # the edit is OK.
        return 1

    def newItemPermission(self, props, classname=None):
        """Determine whether the user has permission to create this item.

        Base behaviour is to check the user can edit this class. No additional
        property checks are made.
        """

        if not classname :
            classname = self.client.classname
        
        if not self.hasPermission('Create', classname=classname):
            return 0

        # Check Create permission for each property, to avoid being able
        # to set restricted ones on new item creation
        for key in props:
            if not self.hasPermission('Create', classname=classname,
                                      property=key):
                return 0
        return 1

class EditItemAction(EditCommon):
    def lastUserActivity(self):
        if ':lastactivity' in self.form:
            d = date.Date(self.form[':lastactivity'].value)
        elif '@lastactivity' in self.form:
            d = date.Date(self.form['@lastactivity'].value)
        else:
            return None
        d.second = int(d.second)
        return d

    def lastNodeActivity(self):
        cl = getattr(self.client.db, self.classname)
        activity = cl.get(self.nodeid, 'activity').local(0)
        activity.second = int(activity.second)
        return activity

    def detectCollision(self, user_activity, node_activity):
        '''Check for a collision and return the list of props we edited
        that conflict.'''
        if user_activity and user_activity < node_activity:
            props, links = self.client.parsePropsFromForm()
            key = (self.classname, self.nodeid)
            # we really only collide for direct prop edit conflicts
            return list(props[key])
        else:
            return []

    def handleCollision(self, props):
        message = self._('Edit Error: someone else has edited this %s (%s). '
            'View <a target="new" href="%s%s">their changes</a> '
            'in a new window.')%(self.classname, ', '.join(props),
            self.classname, self.nodeid)
        self.client.error_message.append(message)
        return

    def handle(self):
        """Perform an edit of an item in the database.

        See parsePropsFromForm and _editnodes for special variables.

        """
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise roundup.exceptions.Reject(self._('Invalid request'))

        user_activity = self.lastUserActivity()
        if user_activity:
            props = self.detectCollision(user_activity, self.lastNodeActivity())
            if props:
                self.handleCollision(props)
                return

        props, links = self.client.parsePropsFromForm()

        # handle the props
        try:
            message = self._editnodes(props, links)
        except (ValueError, KeyError, IndexError,
                roundup.exceptions.Reject), message:
            self.client.error_message.append(
                self._('Edit Error: %s') % str(message))
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
        url += '?@ok_message=%s&@template=%s'%(urllib_.quote(message),
            urllib_.quote(self.template))
        if self.nodeid is None:
            req = templating.HTMLRequest(self.client)
            url += '&' + req.indexargs_url('', {})[1:]
        raise exceptions.Redirect(url)

class NewItemAction(EditCommon):
    def handle(self):
        ''' Add a new item to the database.

            This follows the same form as the EditItemAction, with the same
            special form values.
        '''
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise roundup.exceptions.Reject(self._('Invalid request'))

        # parse the props from the form
        try:
            props, links = self.client.parsePropsFromForm(create=1)
        except (ValueError, KeyError), message:
            self.client.error_message.append(self._('Error: %s')
                % str(message))
            return

        # handle the props - edit or create
        try:
            # when it hits the None element, it'll set self.nodeid
            messages = self._editnodes(props, links)
        except (ValueError, KeyError, IndexError,
                roundup.exceptions.Reject), message:
            # these errors might just be indicative of user dumbness
            self.client.error_message.append(_('Error: %s') % str(message))
            return

        # commit now that all the tricky stuff is done
        self.db.commit()

        # redirect to the new item's page
        raise exceptions.Redirect('%s%s%s?@ok_message=%s&@template=%s' % (
            self.base, self.classname, self.nodeid, urllib_.quote(messages),
            urllib_.quote(self.template)))

class PassResetAction(Action):
    def handle(self):
        """Handle password reset requests.

        Presence of either "name" or "address" generates email. Presence of
        "otk" performs the reset.

        """
        otks = self.db.getOTKManager()
        if 'otk' in self.form:
            # pull the rego information out of the otk database
            otk = self.form['otk'].value
            uid = otks.get(otk, 'uid', default=None)
            if uid is None:
                self.client.error_message.append(
                    self._("Invalid One Time Key!\n"
                        "(a Mozilla bug may cause this message "
                        "to show up erroneously, please check your email)"))
                return

            # re-open the database as "admin"
            if self.user != 'admin':
                self.client.opendb('admin')
                self.db = self.client.db
                otks = self.db.getOTKManager()

            # change the password
            newpw = password.generatePassword()

            cl = self.db.user
            # XXX we need to make the "default" page be able to display errors!
            try:
                # set the password
                cl.set(uid, password=password.Password(newpw, config=self.db.config))
                # clear the props from the otk database
                otks.destroy(otk)
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

            self.client.ok_message.append(
                self._('Password reset and email sent to %s') % address)
            return

        # no OTK, so now figure the user
        if 'username' in self.form:
            name = self.form['username'].value
            try:
                uid = self.db.user.lookup(name)
            except KeyError:
                self.client.error_message.append(self._('Unknown username'))
                return
            address = self.db.user.get(uid, 'address')
        elif 'address' in self.form:
            address = self.form['address'].value
            uid = uidFromAddress(self.db, ('', address), create=0)
            if not uid:
                self.client.error_message.append(
                    self._('Unknown email address'))
                return
            name = self.db.user.get(uid, 'username')
        else:
            self.client.error_message.append(
                self._('You need to specify a username or address'))
            return

        # generate the one-time-key and store the props for later
        otk = ''.join([random.choice(chars) for x in range(32)])
        while otks.exists(otk):
            otk = ''.join([random.choice(chars) for x in range(32)])
        otks.set(otk, uid=uid)
        self.db.commit()

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

        self.client.ok_message.append(self._('Email sent to %s') % address)

class RegoCommon(Action):
    def finishRego(self):
        # log the new user in
        self.client.userid = self.userid
        user = self.client.user = self.db.user.get(self.userid, 'username')
        # re-open the database for real, using the user
        self.client.opendb(user)

        # update session data
        self.client.session_api.set(user=user)

        # nice message
        message = self._('You are now registered, welcome!')
        url = '%suser%s?@ok_message=%s'%(self.base, self.userid,
            urllib_.quote(message))

        # redirect to the user's page (but not 302, as some email clients seem
        # to want to reload the page, or something)
        return '''<html><head><title>%s</title></head>
            <body><p><a href="%s">%s</a></p>
            <script type="text/javascript">
            window.setTimeout('window.location = "%s"', 1000);
            </script>'''%(message, url, message, url)

class ConfRegoAction(RegoCommon):
    def handle(self):
        """Grab the OTK, use it to load up the new user details."""
        try:
            # pull the rego information out of the otk database
            self.userid = self.db.confirm_registration(self.form['otk'].value)
        except (ValueError, KeyError), message:
            self.client.error_message.append(str(message))
            return
        return self.finishRego()

class RegisterAction(RegoCommon, EditCommon):
    name = 'register'
    permissionType = 'Register'

    def handle(self):
        """Attempt to create a new user based on the contents of the form
        and then remember it in session.

        Return 1 on successful login.
        """
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise roundup.exceptions.Reject(self._('Invalid request'))

        # parse the props from the form
        try:
            props, links = self.client.parsePropsFromForm(create=1)
        except (ValueError, KeyError), message:
            self.client.error_message.append(self._('Error: %s')
                % str(message))
            return

        # skip the confirmation step?
        if self.db.config['INSTANT_REGISTRATION']:
            # handle the create now
            try:
                # when it hits the None element, it'll set self.nodeid
                messages = self._editnodes(props, links)
            except (ValueError, KeyError, IndexError,
                    roundup.exceptions.Reject), message:
                # these errors might just be indicative of user dumbness
                self.client.error_message.append(_('Error: %s') % str(message))
                return

            # fix up the initial roles
            self.db.user.set(self.nodeid,
                roles=self.db.config['NEW_WEB_USER_ROLES'])

            # commit now that all the tricky stuff is done
            self.db.commit()

            # finish off by logging the user in
            self.userid = self.nodeid
            return self.finishRego()

        # generate the one-time-key and store the props for later
        user_props = props[('user', None)]
        for propname, proptype in self.db.user.getprops().iteritems():
            value = user_props.get(propname, None)
            if value is None:
                pass
            elif isinstance(proptype, hyperdb.Date):
                user_props[propname] = str(value)
            elif isinstance(proptype, hyperdb.Interval):
                user_props[propname] = str(value)
            elif isinstance(proptype, hyperdb.Password):
                user_props[propname] = str(value)
        otks = self.db.getOTKManager()
        otk = ''.join([random.choice(chars) for x in range(32)])
        while otks.exists(otk):
            otk = ''.join([random.choice(chars) for x in range(32)])
        otks.set(otk, **user_props)

        # send the email
        tracker_name = self.db.config.TRACKER_NAME
        tracker_email = self.db.config.TRACKER_EMAIL
        if self.db.config['EMAIL_REGISTRATION_CONFIRMATION']:
            subject = 'Complete your registration to %s -- key %s'%(tracker_name,
                                                                  otk)
            body = """To complete your registration of the user "%(name)s" with
%(tracker)s, please do one of the following:

- send a reply to %(tracker_email)s and maintain the subject line as is (the
reply's additional "Re:" is ok),

- or visit the following URL:

%(url)s?@action=confrego&otk=%(otk)s

""" % {'name': user_props['username'], 'tracker': tracker_name,
        'url': self.base, 'otk': otk, 'tracker_email': tracker_email}
        else:
            subject = 'Complete your registration to %s'%(tracker_name)
            body = """To complete your registration of the user "%(name)s" with
%(tracker)s, please visit the following URL:

%(url)s?@action=confrego&otk=%(otk)s

""" % {'name': user_props['username'], 'tracker': tracker_name,
        'url': self.base, 'otk': otk}
        if not self.client.standard_message([user_props['address']], subject,
                body, (tracker_name, tracker_email)):
            return

        # commit changes to the database
        self.db.commit()

        # redirect to the "you're almost there" page
        raise exceptions.Redirect('%suser?@template=rego_progress'%self.base)

    def newItemPermission(self, props, classname=None):
        """Just check the "Register" permission.
        """
        # registration isn't allowed to supply roles
        if 'roles' in props:
            raise exceptions.Unauthorised(self._(
                "It is not permitted to supply roles at registration."))

        # technically already checked, but here for clarity
        return self.hasPermission('Register', classname=classname)

class LogoutAction(Action):
    def handle(self):
        """Make us really anonymous - nuke the session too."""
        # log us out
        self.client.make_user_anonymous()
        self.client.session_api.destroy()

        # Let the user know what's going on
        self.client.ok_message.append(self._('You are logged out'))

        # reset client context to render tracker home page
        # instead of last viewed page (may be inaccessibe for anonymous)
        self.client.classname = None
        self.client.nodeid = None
        self.client.template = None

class LoginAction(Action):
    def handle(self):
        """Attempt to log a user in.

        Sets up a session for the user which contains the login credentials.

        """
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise roundup.exceptions.Reject(self._('Invalid request'))

        # we need the username at a minimum
        if '__login_name' not in self.form:
            self.client.error_message.append(self._('Username required'))
            return

        # get the login info
        self.client.user = self.form['__login_name'].value
        if '__login_password' in self.form:
            password = self.form['__login_password'].value
        else:
            password = ''

        try:
            self.verifyLogin(self.client.user, password)
        except exceptions.LoginError, err:
            self.client.make_user_anonymous()
            self.client.error_message.extend(list(err.args))
            return

        # now we're OK, re-open the database for real, using the user
        self.client.opendb(self.client.user)

        # save user in session
        self.client.session_api.set(user=self.client.user)
        if 'remember' in self.form:
            self.client.session_api.update(set_cookie=True, expire=24*3600*365)

        # If we came from someplace, go back there
        if '__came_from' in self.form:
            raise exceptions.Redirect(self.form['__came_from'].value)

    def verifyLogin(self, username, password):
        # make sure the user exists
        try:
            self.client.userid = self.db.user.lookup(username)
        except KeyError:
            raise exceptions.LoginError(self._('Invalid login'))

        # verify the password
        if not self.verifyPassword(self.client.userid, password):
            raise exceptions.LoginError(self._('Invalid login'))

        # Determine whether the user has permission to log in.
        # Base behaviour is to check the user has "Web Access".
        if not self.hasPermission("Web Access"):
            raise exceptions.LoginError(self._(
                "You do not have permission to login"))

    def verifyPassword(self, userid, givenpw):
        '''Verify the password that the user has supplied.
           Optionally migrate to new password scheme if configured
        '''
        db = self.db
        stored = db.user.get(userid, 'password')
        if givenpw == stored:
            if db.config.WEB_MIGRATE_PASSWORDS and stored.needs_migration():
                newpw = password.Password(givenpw, config=db.config)
                db.user.set(userid, password=newpw)
                db.commit()
            return 1
        if not givenpw and not stored:
            return 1
        return 0

class ExportCSVAction(Action):
    name = 'export'
    permissionType = 'View'

    def handle(self):
        ''' Export the specified search query as CSV. '''
        # figure the request
        request = templating.HTMLRequest(self.client)
        filterspec = request.filterspec
        sort = request.sort
        group = request.group
        columns = request.columns
        klass = self.db.getclass(request.classname)

        # full-text search
        if request.search_text:
            matches = self.db.indexer.search(
                re.findall(r'\b\w{2,25}\b', request.search_text), klass)
        else:
            matches = None

        h = self.client.additional_headers
        h['Content-Type'] = 'text/csv; charset=%s' % self.client.charset
        # some browsers will honor the filename here...
        h['Content-Disposition'] = 'inline; filename=query.csv'

        self.client.header()

        if self.client.env['REQUEST_METHOD'] == 'HEAD':
            # all done, return a dummy string
            return 'dummy'

        wfile = self.client.request.wfile
        if self.client.charset != self.client.STORAGE_CHARSET:
            wfile = codecs.EncodedFile(wfile,
                self.client.STORAGE_CHARSET, self.client.charset, 'replace')

        writer = csv.writer(wfile)
        self.client._socket_op(writer.writerow, columns)

        # and search
        for itemid in klass.filter(matches, filterspec, sort, group):
            row = []
            for name in columns:
                # check permission to view this property on this item
                if not self.hasPermission('View', itemid=itemid,
                        classname=request.classname, property=name):
                    raise exceptions.Unauthorised(self._(
                        'You do not have permission to view %(class)s'
                    ) % {'class': request.classname})
                row.append(str(klass.get(itemid, name)))
            self.client._socket_op(writer.writerow, row)

        return '\n'


class Bridge(BaseAction):
    """Make roundup.actions.Action executable via CGI request.

    Using this allows users to write actions executable from multiple frontends.
    CGI Form content is translated into a dictionary, which then is passed as
    argument to 'handle()'. XMLRPC requests have to pass this dictionary
    directly.
    """

    def __init__(self, *args):

        # As this constructor is callable from multiple frontends, each with
        # different Action interfaces, we have to look at the arguments to
        # figure out how to complete construction.
        if (len(args) == 1 and
            hasattr(args[0], '__class__') and
            args[0].__class__.__name__ == 'Client'):
            self.cgi = True
            self.execute = self.execute_cgi
            self.client = args[0]
            self.form = self.client.form
        else:
            self.cgi = False

    def execute_cgi(self):
        args = {}
        for key in self.form:
            args[key] = self.form.getvalue(key)
        self.permission(args)
        return self.handle(args)

    def permission(self, args):
        """Raise Unauthorised if the current user is not allowed to execute
        this action. Users may override this method."""

        pass

    def handle(self, args):

        raise NotImplementedError

# vim: set filetype=python sts=4 sw=4 et si :
