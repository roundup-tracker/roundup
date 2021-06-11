import re, cgi, time, csv, codecs, sys

from roundup import hyperdb, token, date, password
from roundup.actions import Action as BaseAction
from roundup.i18n import _
from roundup.cgi import exceptions, templating
from roundup.mailgw import uidFromAddress
from roundup.rate_limit import Gcra, RateLimit
from roundup.cgi.timestamp import Timestamped
from roundup.exceptions import Reject, RejectRaw
from roundup.anypy import urllib_
from roundup.anypy.strings import StringIO
import roundup.anypy.random_ as random_

from roundup.anypy.html import html_escape

from datetime import timedelta

# Also add action to client.py::Client.actions property
__all__ = ['Action', 'ShowAction', 'RetireAction', 'RestoreAction',
           'SearchAction',
           'EditCSVAction', 'EditItemAction', 'PassResetAction',
           'ConfRegoAction', 'RegisterAction', 'LoginAction', 'LogoutAction',
           'NewItemAction', 'ExportCSVAction', 'ExportCSVWithIdAction']

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
        self.loginLimit = RateLimit(client.db.config.WEB_LOGIN_ATTEMPTS_MIN,
                                    timedelta(seconds=60))

    def handle(self):
        """Action handler procedure"""
        raise NotImplementedError

    def execute(self):
        """Execute the action specified by this object."""
        self.permission()
        return self.handle()

    def examine_url(self, url):
        '''Return URL validated to be under self.base and properly escaped

        If url not properly escaped or validation fails raise ValueError.

        To try to prevent XSS attacks, validate that the url that is
        passed in is under self.base for the tracker. This is used to
        clean up "__came_from" and "__redirect_to" form variables used
        by the LoginAction and NewItemAction actions.

        The url that is passed in must be a properly url quoted
        argument. I.E. all characters that are not valid according to
        RFC3986 must be % encoded. Schema should be lower case.

        It parses the passed url into components.

        It verifies that the scheme is http or https (so a redirect can
        force https even if normal access to the tracker is via http).
        Validates that the network component is the same as in self.base.
        Validates that the path component in the base url starts the url's
        path component. It not it raises ValueError. If everything
        validates:

        For each component, Appendix A of RFC 3986 says the following
        are allowed:

        pchar         = unreserved / pct-encoded / sub-delims / ":" / "@"
        query         = *( pchar / "/" / "?" )
        unreserved    = ALPHA / DIGIT / "-" / "." / "_" / "~"
        pct-encoded   = "%" HEXDIG HEXDIG
        sub-delims    = "!" / "$" / "&" / "'" / "(" / ")"
                         / "*" / "+" / "," / ";" / "="

        Checks all parts with a regexp that matches any run of 0 or
        more allowed characters. If the component doesn't validate,
        raise ValueError. Don't attempt to urllib_.quote it. Either
        it's correct as it comes in or it's a ValueError.

        Finally paste the whole thing together and return the new url.
        '''

        parsed_url_tuple = urllib_.urlparse(url)
        if self.base:
            parsed_base_url_tuple = urllib_.urlparse(self.base)
        else:
            raise ValueError(self._("Base url not set. Check configuration."))

        info = {'url': url,
                'base_url': self.base,
                'base_scheme': parsed_base_url_tuple.scheme,
                'base_netloc': parsed_base_url_tuple.netloc,
                'base_path': parsed_base_url_tuple.path,
                'url_scheme': parsed_url_tuple.scheme,
                'url_netloc': parsed_url_tuple.netloc,
                'url_path': parsed_url_tuple.path,
                'url_params': parsed_url_tuple.params,
                'url_query': parsed_url_tuple.query,
                'url_fragment': parsed_url_tuple.fragment}

        if parsed_base_url_tuple.scheme == "https":
            if parsed_url_tuple.scheme != "https":
                raise ValueError(self._("Base url %(base_url)s requires https."
                                        " Redirect url %(url)s uses http.") %
                                 info)
        else:
            if parsed_url_tuple.scheme not in ('http', 'https'):
                raise ValueError(self._("Unrecognized scheme in %(url)s") %
                                 info)

        if parsed_url_tuple.netloc != parsed_base_url_tuple.netloc:
            raise ValueError(self._("Net location in %(url)s does not match "
                                    "base: %(base_netloc)s") % info)

        if parsed_url_tuple.path.find(parsed_base_url_tuple.path) != 0:
            raise ValueError(self._("Base path %(base_path)s is not a "
                                    "prefix for url %(url)s") % info)

        # I am not sure if this has to be language sensitive.
        # Do ranges depend on the LANG of the user??
        # Is there a newer spec for URI's than what I am referencing?

        # Also it really should be % HEXDIG HEXDIG that's allowed
        # If %%% passes, the roundup server should be able to ignore/
        # quote it so it doesn't do anything bad otherwise we have a
        # different vector to handle.
        allowed_pattern = re.compile(r'''^[A-Za-z0-9@:/?._~%!$&'()*+,;=-]*$''')

        if not allowed_pattern.match(parsed_url_tuple.path):
           raise ValueError(self._("Path component (%(url_path)s) in %(url)s "
                                   "is not properly escaped") % info)

        if not allowed_pattern.match(parsed_url_tuple.params):
           raise ValueError(self._("Params component (%(url_params)s) in %(url)s is not properly escaped") % info)

        if not allowed_pattern.match(parsed_url_tuple.query):
            raise ValueError(self._("Query component (%(url_query)s) in %(url)s is not properly escaped") % info)

        if not allowed_pattern.match(parsed_url_tuple.fragment):
            raise ValueError(self._("Fragment component (%(url_fragment)s) in %(url)s is not properly escaped") % info)

        return(urllib_.urlunparse(parsed_url_tuple))

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
                '%(action)s the %(classname)s class.') % info)

    _marker = []

    def hasPermission(self, permission, classname=_marker, itemid=None,
                      property=None):
        """Check whether the user has 'permission' on the current class."""
        if classname is self._marker:
            classname = self.client.classname
        return self.db.security.hasPermission(permission, self.client.userid,
                                              classname=classname,
                                              itemid=itemid, property=property)

    def gettext(self, msgid):
        """Return the localized translation of msgid"""
        return self.client.translator.gettext(msgid)

    _ = gettext


class ShowAction(Action):

    typere = re.compile('[@:]type')
    numre = re.compile('[@:]number')

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
                '"%(input)s" is not an ID (%(classname)s ID required)') % d)
        url = '%s%s%s' % (self.base, t, n)
        raise exceptions.Redirect(url)


class RetireAction(Action):
    name = 'retire'
    permissionType = 'Edit'

    def handle(self):
        """Retire the context item."""
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise Reject(self._('Invalid request'))

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

        self.client.add_ok_message(
            self._('%(classname)s %(itemid)s has been retired') % {
                'classname': self.classname.capitalize(), 'itemid': itemid})


class RestoreAction(Action):
    name = 'restore'
    permissionType = 'Edit'

    def handle(self):
        """Restore the context item."""
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise Reject(self._('Invalid request'))

        # if we want to view the index template now, then unset the itemid
        # context info (a special-case for retire actions on the index page)
        itemid = self.nodeid
        if self.template == 'index':
            self.client.nodeid = None

        # check permission
        if not self.hasPermission('Restore', classname=self.classname,
                                  itemid=itemid):
            raise exceptions.Unauthorised(self._(
                'You do not have permission to restore %(class)s'
            ) % {'class': self.classname})

        # do the restore
        self.db.getclass(self.classname).restore(itemid)
        self.db.commit()

        self.client.add_ok_message(
            self._('%(classname)s %(itemid)s has been restored') % {
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
                # Note that use of queryname as key will automatically
                # raise an error if there are duplicate names.
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
                uid = self.db.getuid()

                # if the queryname is being changed from the old
                # (original) value, make sure new queryname is not
                # already in use by user.
                # if in use, return to edit/search screen and let
                # user change it.

                if old_queryname != queryname:
                    # we have a name change
                    qids = self.db.query.filter(None, {'name': queryname,
                                                       'creator': uid})
                    for qid in qids:
                        # require an exact name match
                        if queryname != self.db.query.get(qid, 'name'):
                            continue
                        # whoops we found a duplicate; report error and return
                        message = _("You already own a query named '%s'. "
                                    "Please choose another name.") % \
                                    (queryname)
                        self.client.add_error_message(message)
                        return

                # edit the new way, query name not a key any more
                # see if we match an existing private query
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
                                               klass=self.classname, url=url,
                                               private_for=uid)

            # and add it to the user's query multilink
            queries = self.db.user.get(self.userid, 'queries')
            if qid not in queries:
                queries.append(qid)
                self.db.user.set(self.userid, queries=queries)

            # commit the query change to the database
            self.db.commit()

            # This redirects to the index page. Add the @dispname
            # url param to the request so that the query name
            # is displayed.
            req.form.list.append(
                cgi.MiniFieldStorage(
                    "@dispname", queryname
                )
            )

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
                    # If this ever has unbalanced quotes, hilarity will ensue
                    l = token.token_split(v)
                    if len(l) != 1 or l[0] != v:
                        self.form.value.remove(self.form[key])
                        # replace the single value with the split list
                        for v in l:
                            self.form.value.append(cgi.MiniFieldStorage(key, v))
                elif isinstance(prop, hyperdb.Number):
                    try:
                        float(self.form[key].value)
                    except ValueError:
                        raise exceptions.FormError(_("Invalid number: ") +
                                                   self.form[key].value)
                elif isinstance(prop, hyperdb.Integer):
                    try:
                        val = self.form[key].value
                        if (str(int(val)) == val):
                            pass
                        else:
                            raise ValueError
                    except ValueError:
                        raise exceptions.FormError(_("Invalid integer: ") +
                                                   val)

            self.form.value.append(cgi.MiniFieldStorage('@filter', key))

    def getCurrentURL(self, req):
        """Get current URL for storing as a query.

        Note: We are removing the first character from the current URL,
        because the leading '?' is not part of the query string.

        Implementation note:
        We now store the template with the query if the template name is
        different from 'index'
        """
        template = self.getFromForm('template')
        if template and template != 'index':
            return req.indexargs_url('', {'@template': template})[1:]
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
            raise Reject(self._('Invalid request'))

        # figure the properties list for the class
        cl = self.db.classes[self.classname]
        props_without_id = list(cl.getprops(protected=0))

        # the incoming CSV data will always have the properties in colums
        # sorted and starting with the "id" column
        props_without_id.sort()
        props = ['id'] + props_without_id

        # do the edit
        rows = StringIO(self.form['rows'].value)
        reader = csv.reader(rows)
        found = {}
        line = 0
        for values in reader:
            line += 1
            if line == 1: continue
            # skip property names header
            if values == props:
                continue
            # skip blank lines. Can be in the middle
            # of the data or a newline at end of file.
            if len(values) == 0:
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
                exists = 1
            else:
                exists = 1

            # confirm correct weight
            if len(props_without_id) != len(values):
                self.client.add_error_message(
                    self._('Not enough values on line %(line)s') % \
                    {'line':line})
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
                    elif isinstance(prop, hyperdb.Integer):
                        value = int(value)
                    d[name] = value
                elif exists:
                    # nuke the existing value
                    if isinstance(prop, hyperdb.Multilink):
                        d[name] = []
                    elif isinstance(prop, hyperdb.Password):
                        # create empty password entry
                        d[name] = password.Password("", config=self.db.config)
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

        self.client.add_ok_message(self._('Items edited OK'))


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
            numeric_id = int(nodeid or 0)
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
                            % {'class': cn, 'id': nodeid, 'properties': info})
                    else:
                        # this used to produce a message like:
                        #    issue34 - nothing changed
                        # which is confusing if only quiet properties
                        # changed for the class/id. So don't report
                        # anything if the user didn't explicitly change
                        # a visible (non-quiet) property.
                        pass
                else:
                    # make a new node
                    newid = self._createnode(cn, props)
                    if nodeid is None:
                        self.nodeid = newid
                    nodeid = newid

                    # and some nice feedback for the user
                    m.append(self._('%(class)s %(id)s created')
                             % {'class': cn, 'id': newid})

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
                    elif isinstance(propdef, hyperdb.Multilink):
                        props[linkprop].append(nodeid)

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

        if not classname:
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
        message = self._(
            'Edit Error: someone else has edited this %(klass)s (%(props)s). '
            'View <a target="_blank" href="%(klass)s%(id)s">their changes</a> '
            'in a new window.') % { "klass": self.classname,
                                    "props": ', '.join(props),
                                    "id": self.nodeid}
        self.client.add_error_message(message, escape=False)
        return

    def handle(self):
        """Perform an edit of an item in the database.

        See parsePropsFromForm and _editnodes for special variables.

        """
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise Reject(self._('Invalid request'))

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
        except (ValueError, KeyError, IndexError, Reject) as message:
            escape = not isinstance(message, RejectRaw)
            self.client.add_error_message(
                self._('Edit Error: %s') % str(message), escape=escape)
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
        url += '?@ok_message=%s&@template=%s' % (urllib_.quote(message),
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
            raise Reject(self._('Invalid request'))

        # parse the props from the form
        try:
            props, links = self.client.parsePropsFromForm(create=1)
        except (ValueError, KeyError) as message:
            self.client.add_error_message(self._('Error: %s')
                                          % str(message))
            return

        # handle the props - edit or create
        try:
            # when it hits the None element, it'll set self.nodeid
            messages = self._editnodes(props, links)
        except (ValueError, KeyError, IndexError, Reject) as message:
            escape = not isinstance(message, RejectRaw)
            # these errors might just be indicative of user dumbness
            self.client.add_error_message(_('Error: %s') % str(message),
                                          escape=escape)
            return

        # commit now that all the tricky stuff is done
        self.db.commit()

        # Allow an option to stay on the page to create new things
        if '__redirect_to' in self.form:
            raise exceptions.Redirect('%s&@ok_message=%s' % (
                self.examine_url(self.form['__redirect_to'].value),
                urllib_.quote(messages)))

        # otherwise redirect to the new item's page
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
                self.client.add_error_message(
                    self._("Invalid One Time Key!\n"
                           "(a Mozilla bug may cause this message "
                           "to show up erroneously, please check your email)"))
                return

            # pull the additional email address if exist
            uaddress = otks.get(otk, 'uaddress', default=None)

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
                cl.set(uid, password=password.Password(newpw,
                                                       config=self.db.config))
                # clear the props from the otk database
                otks.destroy(otk)
                otks.commit()
                # commit the password change
                self.db.commit()
            except (ValueError, KeyError) as message:
                self.client.add_error_message(str(message))
                return

            # user info
            name = self.db.user.get(uid, 'username')
            if uaddress is None:
                address = self.db.user.get(uid, 'address')
            else:
                address = uaddress

            # send the email
            tracker_name = self.db.config.TRACKER_NAME
            subject = 'Password reset for %s' % tracker_name
            body = '''
The password has been reset for username "%(name)s".

Your password is now: %(password)s
''' % {'name': name, 'password': newpw}
            if not self.client.standard_message([address], subject, body):
                return

            self.client.add_ok_message(
                self._('Password reset and email sent to %s') % address)
            return

        # no OTK, so now figure the user
        if 'username' in self.form:
            name = self.form['username'].value
            try:
                uid = self.db.user.lookup(name)
            except KeyError:
                self.client.add_error_message(self._('Unknown username'))
                return
            address = self.db.user.get(uid, 'address')
        elif 'address' in self.form:
            address = self.form['address'].value
            uid = uidFromAddress(self.db, ('', address), create=0)
            if not uid:
                self.client.add_error_message(
                    self._('Unknown email address'))
                return
            name = self.db.user.get(uid, 'username')
        else:
            self.client.add_error_message(
                self._('You need to specify a username or address'))
            return

        # generate the one-time-key and store the props for later
        otk = ''.join([random_.choice(chars) for x in range(32)])
        while otks.exists(otk):
            otk = ''.join([random_.choice(chars) for x in range(32)])
        otks.set(otk, uid=uid, uaddress=address)
        otks.commit()

        # send the email
        tracker_name = self.db.config.TRACKER_NAME
        subject = 'Confirm reset of password for %s' % tracker_name
        body = '''
Someone, perhaps you, has requested that the password be changed for your
username, "%(name)s". If you wish to proceed with the change, please follow
the link below:

  %(url)suser?@template=forgotten&@action=passrst&otk=%(otk)s

You should then receive another email with the new password.
''' % {'name': name, 'tracker': tracker_name, 'url': self.base, 'otk': otk}
        if not self.client.standard_message([address], subject, body):
            return

        if 'username' in self.form:
            self.client.add_ok_message(self._('Email sent to primary notification address for %s.') % name)
        else:
            self.client.add_ok_message(self._('Email sent to %s.') % address)


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
        url = '%suser%s?@ok_message=%s' % (self.base, self.userid,
                                           urllib_.quote(message))

        # redirect to the user's page (but not 302, as some email clients seem
        # to want to reload the page, or something)
        return '''<html><head><title>%s</title></head>
            <body><p><a href="%s">%s</a></p>
            <script nonce="%s" type="text/javascript">
            window.setTimeout('window.location = "%s"', 1000);
            </script>''' % (message, url, message,
                          self.client.client_nonce, url)


class ConfRegoAction(RegoCommon):
    def handle(self):
        """Grab the OTK, use it to load up the new user details."""
        try:
            # pull the rego information out of the otk database
            self.userid = self.db.confirm_registration(self.form['otk'].value)
        except (ValueError, KeyError) as message:
            self.client.add_error_message(str(message))
            return
        return self.finishRego()


class RegisterAction(RegoCommon, EditCommon, Timestamped):
    name = 'register'
    permissionType = 'Register'

    def handle(self):
        """Attempt to create a new user based on the contents of the form
        and then remember it in session.

        Return 1 on successful login.
        """
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise Reject(self._('Invalid request'))

        # try to make sure user is not a bot by checking the
        # hidden field opaqueregister to make sure it's at least
        # WEB_REGISTRATION_DELAY seconds. If set to 0,
        # disable the check.
        delaytime = self.db.config['WEB_REGISTRATION_DELAY']

        if delaytime > 0:
            self.timecheck('opaqueregister', delaytime)

        # parse the props from the form
        try:
            props, links = self.client.parsePropsFromForm(create=1)
        except (ValueError, KeyError) as message:
            self.client.add_error_message(self._('Error: %s')
                                          % str(message))
            return

        # skip the confirmation step?
        if self.db.config['INSTANT_REGISTRATION']:
            # handle the create now
            try:
                # when it hits the None element, it'll set self.nodeid
                messages = self._editnodes(props, links)
            except (ValueError, KeyError, IndexError, Reject) as message:
                escape = not isinstance(message, RejectRaw)
                # these errors might just be indicative of user dumbness
                self.client.add_error_message(_('Error: %s') % str(message),
                                              escape=escape)
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
        # check that admin has requested username available check
        check_user = self.db.config['WEB_REGISTRATION_PREVALIDATE_USERNAME']
        if check_user:
            try:
                user_found = self.db.user.lookup(user_props['username'])
                # if user is found reject the request.
                raise Reject(
                    _("Username '%s' is already used.") % user_props['username'])
            except KeyError:
                # user not found this is what we want.
                pass

        for propname, proptype in self.db.user.getprops().items():
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
        otk = ''.join([random_.choice(chars) for x in range(32)])
        while otks.exists(otk):
            otk = ''.join([random_.choice(chars) for x in range(32)])
        otks.set(otk, **user_props)

        # send the email
        tracker_name = self.db.config.TRACKER_NAME
        tracker_email = self.db.config.TRACKER_EMAIL
        if self.db.config['EMAIL_REGISTRATION_CONFIRMATION']:
            subject = 'Complete your registration to %s -- key %s' % (
                tracker_name, otk)
            body = """To complete your registration of the user "%(name)s" with
%(tracker)s, please do one of the following:

- send a reply to %(tracker_email)s and maintain the subject line as is (the
reply's additional "Re:" is ok),

- or visit the following URL:

%(url)s?@action=confrego&otk=%(otk)s

""" % {'name': user_props['username'], 'tracker': tracker_name,
       'url': self.base, 'otk': otk, 'tracker_email': tracker_email}
        else:
            subject = 'Complete your registration to %s' % (tracker_name)
            body = """To complete your registration of the user "%(name)s" with
%(tracker)s, please visit the following URL:

%(url)s?@action=confrego&otk=%(otk)s

""" % {'name': user_props['username'], 'tracker': tracker_name,
       'url': self.base, 'otk': otk}
        if not self.client.standard_message([user_props['address']], subject,
                                            body,
                                            (tracker_name, tracker_email)):
            return

        # commit changes to the database
        self.db.commit()

        # redirect to the "you're almost there" page
        raise exceptions.Redirect('%suser?@template=rego_progress' % self.base)

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
        self.client.add_ok_message(self._('You are logged out'))

        # reset client context to render tracker home page
        # instead of last viewed page (may be inaccessibe for anonymous)
        self.client.classname = None
        self.client.nodeid = None
        self.client.template = None

        # Redirect to a new page on logout. This regenerates
        # CSRF tokens so they are associated with the
        # anonymous user and not the user who logged out. If
        # we don't the user gets an invalid CSRF token error
        # As above choose the home page since everybody can
        # see that.
        raise exceptions.Redirect(self.base)


class LoginAction(Action):
    def handle(self):
        """Attempt to log a user in.

        Sets up a session for the user which contains the login credentials.

        """
        # ensure modification comes via POST
        if self.client.env['REQUEST_METHOD'] != 'POST':
            raise Reject(self._('Invalid request'))

        # we need the username at a minimum
        if '__login_name' not in self.form:
            self.client.add_error_message(self._('Username required'))
            return

        # get the login info
        self.client.user = self.form['__login_name'].value
        if '__login_password' in self.form:
            password = self.form['__login_password'].value
        else:
            password = ''

        if '__came_from' in self.form:
            # On valid or invalid login, redirect the user back to the page
            # the started on. Searches, issue and other pages
            # are all preserved in __came_from. Clean out any old feedback
            # @error_message, @ok_message from the __came_from url.
            #
            # 1. Split the url into components.
            # 2. Split the query string into parts.
            # 3. Delete @error_message and @ok_message if present.
            # 4. Define a new redirect_url missing the @...message entries.
            #    This will be redefined if there is a login error to include
            #      a new error message

            clean_url = self.examine_url(self.form['__came_from'].value)
            redirect_url_tuple = urllib_.urlparse(clean_url)
            # now I have a tuple form for the __came_from url
            try:
                query = urllib_.parse_qs(redirect_url_tuple.query)
                if "@error_message" in query:
                    del query["@error_message"]
                if "@ok_message" in query:
                    del query["@ok_message"]
                if "@action" in query:
                    # also remove the logout action from the redirect
                    # there is only ever one @action value.
                    if query['@action'] == ["logout"]:
                        del query["@action"]
            except AttributeError:
                # no query param so nothing to remove. Just define.
                query = {}
                pass

            redirect_url = urllib_.urlunparse((redirect_url_tuple.scheme,
                                               redirect_url_tuple.netloc,
                                               redirect_url_tuple.path,
                                               redirect_url_tuple.params,
                                               urllib_.urlencode(list(sorted(query.items())), doseq=True),
                                               redirect_url_tuple.fragment)
            )

        try:
            # Implement rate limiting of logins by login name.
            # Use prefix to prevent key collisions maybe??
            # set client.db.config.WEB_LOGIN_ATTEMPTS_MIN to 0
            #  to disable
            if self.client.db.config.WEB_LOGIN_ATTEMPTS_MIN:  # if 0 - off
                rlkey = "LOGIN-" + self.client.user
                limit = self.loginLimit
                gcra = Gcra()
                otk = self.client.db.Otk
                try:
                    val = otk.getall(rlkey)
                    gcra.set_tat_as_string(rlkey, val['tat'])
                except KeyError:
                    # ignore if tat not set, it's 1970-1-1 by default.
                    pass
                # see if rate limit exceeded and we need to reject the attempt
                reject = gcra.update(rlkey, limit)

                # Calculate a timestamp that will make OTK expire the
                # unused entry 1 hour in the future
                ts = time.time() - (60 * 60 * 24 * 7) + 3600
                otk.set(rlkey, tat=gcra.get_tat_as_string(rlkey),
                        __timestamp=ts)
                otk.commit()

                if reject:
                    # User exceeded limits: find out how long to wait
                    status = gcra.status(rlkey, limit)
                    raise Reject(_("Logins occurring too fast. Please wait: %s seconds.") % status['Retry-After'])

            self.verifyLogin(self.client.user, password)
        except exceptions.LoginError as err:
            self.client.make_user_anonymous()
            for arg in err.args:
                self.client.add_error_message(arg)

            if '__came_from' in self.form:
                # set a new error
                query['@error_message'] = err.args
                redirect_url = urllib_.urlunparse((redirect_url_tuple.scheme,
                                                   redirect_url_tuple.netloc,
                                                   redirect_url_tuple.path,
                                                   redirect_url_tuple.params,
                                                   urllib_.urlencode(list(sorted(query.items())), doseq=True),
                                                   redirect_url_tuple.fragment )
                )
                raise exceptions.Redirect(redirect_url)
            # if no __came_from, send back to base url with error
            return

        # now we're OK, re-open the database for real, using the user
        self.client.opendb(self.client.user)

        # save user in session
        self.client.session_api.set(user=self.client.user)
        if 'remember' in self.form:
            self.client.session_api.update(set_cookie=True, expire=24*3600*365)

        # If we came from someplace, go back there
        if '__came_from' in self.form:
            raise exceptions.Redirect(redirect_url)

    def verifyLogin(self, username, password):
        # make sure the user exists
        try:
            self.client.userid = self.db.user.lookup(username)
        except KeyError:
            # Perform password check against anonymous user.
            # Prevents guessing of valid usernames by detecting
            # delay caused by checking password only on valid
            # users.
            _discard = self.verifyPassword("2", password)
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
    list_sep = ';'              # Separator for list types

    def handle(self):
        ''' Export the specified search query as CSV. '''
        # figure the request
        request = templating.HTMLRequest(self.client)
        filterspec = request.filterspec
        sort = request.sort
        group = request.group
        columns = request.columns
        klass = self.db.getclass(request.classname)

        # check if all columns exist on class
        # the exception must be raised before sending header
        props = klass.getprops()
        for cname in columns:
            if cname not in props:
                # use error code 400: Bad Request. Do not use
                # error code 404: Not Found.
                self.client.response_code = 400
                raise exceptions.NotFound(
                    self._('Column "%(column)s" not found in %(class)s')
                    % {'column': html_escape(cname),
                       'class': request.classname})

        # full-text search
        if request.search_text:
            matches = self.db.indexer.search(
                re.findall(r'\b\w{2,25}\b', request.search_text), klass)
        else:
            matches = None

        header = self.client.additional_headers
        header['Content-Type'] = 'text/csv; charset=%s' % self.client.charset
        # some browsers will honor the filename here...
        header['Content-Disposition'] = 'inline; filename=query.csv'

        self.client.header()

        if self.client.env['REQUEST_METHOD'] == 'HEAD':
            # all done, return a dummy string
            return 'dummy'

        wfile = self.client.request.wfile
        if sys.version_info[0] > 2:
            wfile = codecs.getwriter(self.client.charset)(wfile, 'replace')
        elif self.client.charset != self.client.STORAGE_CHARSET:
            wfile = codecs.EncodedFile(wfile,
                                       self.client.STORAGE_CHARSET,
                                       self.client.charset, 'replace')

        writer = csv.writer(wfile, quoting=csv.QUOTE_NONNUMERIC)

        # handle different types of columns.
        def repr_no_right(cls, col):
            """User doesn't have the right to see the value of col."""
            def fct(arg):
                return "[hidden]"
            return fct

        def repr_link(cls, col):
            """Generate a function which returns the string representation of
            a link depending on `cls` and `col`."""
            def fct(arg):
                if arg is None:
                    return ""
                else:
                    return str(cls.get(arg, col))
            return fct

        def repr_list(cls, col):
            def fct(arg):
                if arg is None:
                    return ""
                elif type(arg) is list:
                    seq = [str(cls.get(val, col)) for val in arg]
                    # python2/python 3 have different order in lists
                    # sort to not break tests
                    seq.sort()
                    return self.list_sep.join(seq)
            return fct

        def repr_date():
            def fct(arg):
                if arg is None:
                    return ""
                else:
                    if (arg.local(self.db.getUserTimezone()).pretty('%H:%M') ==
                        '00:00'):
                        fmt = '%Y-%m-%d'
                    else:
                        fmt = '%Y-%m-%d %H:%M'
                return arg.local(self.db.getUserTimezone()).pretty(fmt)
            return fct

        def repr_val():
            def fct(arg):
                if arg is None:
                    return ""
                else:
                    return str(arg)
            return fct

        props = klass.getprops()

        # Determine translation map.
        ncols = []
        represent = {}
        for col in columns:
            ncols.append(col)
            represent[col] = repr_val()
            if isinstance(props[col], hyperdb.Multilink):
                cname = props[col].classname
                cclass = self.db.getclass(cname)
                represent[col] = repr_list(cclass, 'name')
                if not self.hasPermission(self.permissionType, classname=cname):
                    represent[col] = repr_no_right(cclass, 'name')
                else:
                    if 'name' in cclass.getprops():
                        represent[col] = repr_list(cclass, 'name')
                    elif cname == 'user':
                        represent[col] = repr_list(cclass, 'realname')
            if isinstance(props[col], hyperdb.Link):
                cname = props[col].classname
                cclass = self.db.getclass(cname)
                if not self.hasPermission(self.permissionType, classname=cname):
                    represent[col] = repr_no_right(cclass, 'name')
                else:
                    if 'name' in cclass.getprops():
                        represent[col] = repr_link(cclass, 'name')
                    elif cname == 'user':
                        represent[col] = repr_link(cclass, 'realname')
            if isinstance(props[col], hyperdb.Date):
                represent[col] = repr_date()

        columns = ncols
        # generate the CSV output
        self.client._socket_op(writer.writerow, columns)
        # and search
        for itemid in klass.filter(matches, filterspec, sort, group):
            row = []
            # don't put out a row of [hidden] fields if the user has
            # no access to the issue.
            if not self.hasPermission(self.permissionType, itemid=itemid,
                                      classname=request.classname):
                continue
            for name in columns:
                # check permission for this property on this item
                # TODO: Permission filter doesn't work for the 'user' class
                if not self.hasPermission(self.permissionType, itemid=itemid,
                                          classname=request.classname,
                                          property=name):
                    repr_function = repr_no_right(request.classname, name)
                else:
                    repr_function = represent[name]
                row.append(repr_function(klass.get(itemid, name)))
            self.client._socket_op(writer.writerow, row)
        return '\n'


class ExportCSVWithIdAction(Action):
    ''' A variation of ExportCSVAction that returns ID number rather than
        names. This is the original csv export function.
    '''
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

        # check if all columns exist on class
        # the exception must be raised before sending header
        props = klass.getprops()
        for cname in columns:
            if cname not in props:
                # use error code 400: Bad Request. Do not use
                # error code 404: Not Found.
                self.client.response_code = 400
                raise exceptions.NotFound(
                    self._('Column "%(column)s" not found in %(class)s')
                    % {'column': html_escape(cname),
                       'class': request.classname})

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
        if sys.version_info[0] > 2:
            wfile = codecs.getwriter(self.client.charset)(wfile, 'replace')
        elif self.client.charset != self.client.STORAGE_CHARSET:
            wfile = codecs.EncodedFile(wfile,
                                       self.client.STORAGE_CHARSET,
                                       self.client.charset, 'replace')

        writer = csv.writer(wfile, quoting=csv.QUOTE_NONNUMERIC)
        self.client._socket_op(writer.writerow, columns)

        # and search
        for itemid in klass.filter(matches, filterspec, sort, group):
            row = []
            # FIXME should this code raise an exception if an item
            # is included that can't be accessed? Enabling this
            # check will just skip the row for the inaccessible item.
            # This makes it act more like the web interface.
            # if not self.hasPermission(self.permissionType, itemid=itemid,
            #                          classname=request.classname):
            #    continue
            for name in columns:
                # check permission to view this property on this item
                if not self.hasPermission(self.permissionType, itemid=itemid,
                                          classname=request.classname,
                                          property=name):
                    # FIXME: is this correct, or should we just
                    # emit a '[hidden]' string. Note that this may
                    # allow an attacker to figure out hidden schema
                    # properties.
                    # A bad property name will result in an exception.
                    # A valid property results in a column of '[hidden]'
                    #   values.
                    raise exceptions.Unauthorised(self._(
                        'You do not have permission to view %(class)s'
                    ) % {'class': request.classname})
                value = klass.get(itemid, name)
                try:
                    # python2/python 3 have different order in lists
                    # sort to not break tests
                    value.sort()
                except AttributeError:
                    pass  # value is not sortable, probably str
                row.append(str(value))
            self.client._socket_op(writer.writerow, row)

        return '\n'


class Bridge(BaseAction):
    """Make roundup.actions.Action executable via CGI request.

    Using this allows users to write actions executable from multiple
    frontends. CGI Form content is translated into a dictionary, which
    then is passed as argument to 'handle()'. XMLRPC requests have to
    pass this dictionary directly.
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
