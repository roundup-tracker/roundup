#
# Copyright (C) 2007 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

from roundup import hyperdb
from roundup.exceptions import Unauthorised, UsageError
from roundup.date import Date, Range, Interval
from roundup import actions
from SimpleXMLRPCServer import SimpleXMLRPCDispatcher
from xmlrpclib import Binary

def translate(value):
    """Translate value to becomes valid for XMLRPC transmission."""

    if isinstance(value, (Date, Range, Interval)):
        return repr(value)
    elif type(value) is list:
        return [translate(v) for v in value]
    elif type(value) is tuple:
        return tuple([translate(v) for v in value])
    elif type(value) is dict:
        return dict([[translate(k), translate(value[k])] for k in value])
    else:
        return value


def props_from_args(db, cl, args, itemid=None):
    """Construct a list of properties from the given arguments,
    and return them after validation."""

    props = {}
    for arg in args:
        if isinstance(arg, Binary):
            arg = arg.data
        try :
            key, value = arg.split('=', 1)
        except ValueError :
            raise UsageError, 'argument "%s" not propname=value'%arg
        if isinstance(key, unicode):
            try:
                key = key.encode ('ascii')
            except UnicodeEncodeError:
                raise UsageError, 'argument %r is no valid ascii keyword'%key
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        if value:
            try:
                props[key] = hyperdb.rawToHyperdb(db, cl, itemid,
                                                  key, value)
            except hyperdb.HyperdbValueError as message:
                raise UsageError, message
        else:
            props[key] = None

    return props

class RoundupInstance:
    """The RoundupInstance provides the interface accessible through
    the Python XMLRPC mapping."""

    def __init__(self, db, actions, translator):

        self.db = db
        self.actions = actions
        self.translator = translator

    def schema(self):
        s = {}
        for c in self.db.classes:
            cls = self.db.classes[c]
            props = [(n,repr(v)) for n,v in cls.properties.items()]
            s[c] = props
        return s

    def list(self, classname, propname=None):
        cl = self.db.getclass(classname)
        if not propname:
            propname = cl.labelprop()
        result = [cl.get(itemid, propname)
                  for itemid in cl.list()
                  if self.db.security.hasPermission('View', self.db.getuid(),
                                                    classname, propname, itemid)
                  ]
        return result

    def filter(self, classname, search_matches, filterspec,
               sort=[], group=[]):
        cl = self.db.getclass(classname)
        uid = self.db.getuid()
        security = self.db.security
        filterspec = security.filterFilterspec (uid, classname, filterspec)
        sort = security.filterSortspec (uid, classname, sort)
        group = security.filterSortspec (uid, classname, group)
        result = cl.filter(search_matches, filterspec, sort=sort, group=group)
        check = security.hasPermission
        x = [id for id in result if check('View', uid, classname, itemid=id)]
        return x

    def lookup(self, classname, key):
        cl = self.db.getclass(classname)
        uid = self.db.getuid()
        prop = cl.getkey()
        search = self.db.security.hasSearchPermission
        access = self.db.security.hasPermission
        if (not search(uid, classname, prop)
           and not access('View', uid, classname, prop)):
           raise Unauthorised('Permission to lookup %s denied'%classname)
        return cl.lookup(key)

    def display(self, designator, *properties):
        classname, itemid = hyperdb.splitDesignator(designator)
        cl = self.db.getclass(classname)
        props = properties and list(properties) or cl.properties.keys()
        props.sort()
        for p in props:
            if not self.db.security.hasPermission('View', self.db.getuid(),
                                                  classname, p, itemid):
                raise Unauthorised('Permission to view %s of %s denied'%
                                   (p, designator))
            result = [(prop, cl.get(itemid, prop)) for prop in props]
        return dict(result)

    def create(self, classname, *args):
        
        if not self.db.security.hasPermission('Create', self.db.getuid(), classname):
            raise Unauthorised('Permission to create %s denied'%classname)

        cl = self.db.getclass(classname)

        # convert types
        props = props_from_args(self.db, cl, args)

        # check for the key property
        key = cl.getkey()
        if key and not props.has_key(key):
            raise UsageError, 'you must provide the "%s" property.'%key

        for key in props:
            if not self.db.security.hasPermission('Create', self.db.getuid(),
                classname, property=key):
                raise Unauthorised('Permission to create %s.%s denied'%(classname, key))

        # do the actual create
        try:
            result = cl.create(**props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise UsageError, message
        return result

    def set(self, designator, *args):

        classname, itemid = hyperdb.splitDesignator(designator)
        cl = self.db.getclass(classname)
        props = props_from_args(self.db, cl, args, itemid) # convert types
        for p in props.iterkeys():
            if not self.db.security.hasPermission('Edit', self.db.getuid(),
                                                  classname, p, itemid):
                raise Unauthorised('Permission to edit %s of %s denied'%
                                   (p, designator))
        try:
            result = cl.set(itemid, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise UsageError, message
        return result


    builtin_actions = {'retire': actions.Retire}

    def action(self, name, *args):
        """Execute a named action."""
        
        if name in self.actions:
            action_type = self.actions[name]
        elif name in self.builtin_actions:
            action_type = self.builtin_actions[name]
        else:
            raise Exception('action "%s" is not supported %s' % (name, ','.join(self.actions.keys())))
        action = action_type(self.db, self.translator)
        return action.execute(*args)


class RoundupDispatcher(SimpleXMLRPCDispatcher):
    """RoundupDispatcher bridges from cgi.client to RoundupInstance.
    It expects user authentication to be done."""

    def __init__(self, db, actions, translator,
                 allow_none=False, encoding=None):
        SimpleXMLRPCDispatcher.__init__(self, allow_none, encoding)
        self.register_instance(RoundupInstance(db, actions, translator))
        self.register_multicall_functions()
                 

    def dispatch(self, input):
        return self._marshaled_dispatch(input)

    def _dispatch(self, method, params):

        retn = SimpleXMLRPCDispatcher._dispatch(self, method, params)
        retn = translate(retn)
        return retn
    
