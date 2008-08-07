#
# Copyright (C) 2007 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

import base64
import roundup.instance
from roundup import hyperdb
from roundup.cgi.exceptions import *
from roundup.admin import UsageError
from SimpleXMLRPCServer import SimpleXMLRPCRequestHandler

class RoundupRequestHandler(SimpleXMLRPCRequestHandler):
    """A SimpleXMLRPCRequestHandler with support for basic
    HTTP Authentication."""

    def do_POST(self):
        """Extract username and password from authorization header."""

        # Try to extract username and password from HTTP Authentication.
        self.username = None
        self.password = None
        authorization = self.headers.get('authorization', ' ')
        scheme, challenge = authorization.split(' ', 1)

        if scheme.lower() == 'basic':
            decoded = base64.decodestring(challenge)
            self.username, self.password = decoded.split(':')

        SimpleXMLRPCRequestHandler.do_POST(self)

    def _dispatch(self, method, params):
        """Inject username and password into function arguments."""

        # Add username and password to function arguments
        params = [self.username, self.password] + list(params)
        return self.server._dispatch(method, params)


class RoundupRequest:
    """Little helper class to handle common per-request tasks such
    as authentication and login."""

    def __init__(self, tracker, username, password):
        """Open the database for the given tracker, using the given
        username and password."""

        self.tracker = tracker
        self.db = self.tracker.open('admin')
        try:
            self.userid = self.db.user.lookup(username)
        except KeyError: # No such user
            self.db.close()
            raise Unauthorised, 'Invalid user'
        stored = self.db.user.get(self.userid, 'password')
        if stored != password:
            # Wrong password
            self.db.close()
            raise Unauthorised, 'Invalid user'
        self.db.setCurrentUser(username)

    def close(self):
        """Close the database, after committing any changes, if needed."""

        try:
            self.db.commit()
        finally:
            self.db.close()

    def get_class(self, classname):
        """Return the class for the given classname."""

        try:
            return self.db.getclass(classname)
        except KeyError:
            raise UsageError, 'no such class "%s"'%classname

    def props_from_args(self, cl, args, itemid=None):
        """Construct a list of properties from the given arguments,
        and return them after validation."""

        props = {}
        for arg in args:
            if arg.find('=') == -1:
                raise UsageError, 'argument "%s" not propname=value'%arg
            l = arg.split('=')
            if len(l) < 2:
                raise UsageError, 'argument "%s" not propname=value'%arg
            key, value = l[0], '='.join(l[1:])
            if value:
                try:
                    props[key] = hyperdb.rawToHyperdb(self.db, cl, itemid,
                        key, value)
                except hyperdb.HyperdbValueError, message:
                    raise UsageError, message
            else:
                props[key] = None

        return props


#The server object
class RoundupServer:
    """The RoundupServer provides the interface accessible through
    the Python XMLRPC mapping. All methods take an additional username
    and password argument so each request can be authenticated."""

    def __init__(self, tracker, verbose = False):
        self.tracker = roundup.instance.open(tracker)
        self.verbose = verbose

    def list(self, username, password, classname, propname=None):
        r = RoundupRequest(self.tracker, username, password)
        try:
            cl = r.get_class(classname)
            if not propname:
                propname = cl.labelprop()
            result = [cl.get(itemid, propname)
                for itemid in cl.list()
                     if r.db.security.hasPermission('View', r.userid,
                         classname, propname, itemid)
            ]
        finally:
            r.close()
        return result

    def filter(self, username, password, classname, search_matches, filterspec,
            sort=[], group=[]):
        r = RoundupRequest(self.tracker, username, password)
        try:
            cl = r.get_class(classname)
            result = cl.filter(search_matches, filterspec, sort=sort, group=group)
        finally:
            r.close()
        return result

    def display(self, username, password, designator, *properties):
        r = RoundupRequest(self.tracker, username, password)
        try:
            classname, itemid = hyperdb.splitDesignator(designator)
            cl = r.get_class(classname)
            props = properties and list(properties) or cl.properties.keys()
            props.sort()
            for p in props:
                if not r.db.security.hasPermission('View', r.userid,
                        classname, p, itemid):
                    raise Unauthorised('Permission to view %s of %s denied'%
                            (p, designator))
            result = [(prop, cl.get(itemid, prop)) for prop in props]
        finally:
            r.close()
        return dict(result)

    def create(self, username, password, classname, *args):
        r = RoundupRequest(self.tracker, username, password)
        try:
            if not r.db.security.hasPermission('Create', r.userid, classname):
                raise Unauthorised('Permission to create %s denied'%classname)

            cl = r.get_class(classname)

            # convert types
            props = r.props_from_args(cl, args)

            # check for the key property
            key = cl.getkey()
            if key and not props.has_key(key):
                raise UsageError, 'you must provide the "%s" property.'%key

            # do the actual create
            try:
                result = cl.create(**props)
            except (TypeError, IndexError, ValueError), message:
                raise UsageError, message
        finally:
            r.close()
        return result

    def set(self, username, password, designator, *args):
        r = RoundupRequest(self.tracker, username, password)
        try:
            classname, itemid = hyperdb.splitDesignator(designator)
            cl = r.get_class(classname)
            props = r.props_from_args(cl, args, itemid) # convert types
            for p in props.iterkeys ():
                if not r.db.security.hasPermission('Edit', r.userid,
                        classname, p, itemid):
                    raise Unauthorised('Permission to edit %s of %s denied'%
                        (p, designator))
            try:
                return cl.set(itemid, **props)
            except (TypeError, IndexError, ValueError), message:
                raise UsageError, message
        finally:
            r.close()

# vim: set et sts=4 sw=4 :
