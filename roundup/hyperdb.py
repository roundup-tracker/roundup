#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
# $Id: hyperdb.py,v 1.46 2002-01-07 10:42:23 richard Exp $

__doc__ = """
Hyperdatabase implementation, especially field types.
"""

# standard python modules
import cPickle, re, string, weakref

# roundup modules
import date, password


#
# Types
#
class String:
    """An object designating a String property."""
    def __repr__(self):
        return '<%s>'%self.__class__

class Password:
    """An object designating a Password property."""
    def __repr__(self):
        return '<%s>'%self.__class__

class Date:
    """An object designating a Date property."""
    def __repr__(self):
        return '<%s>'%self.__class__

class Interval:
    """An object designating an Interval property."""
    def __repr__(self):
        return '<%s>'%self.__class__

class Link:
    """An object designating a Link property that links to a
       node in a specified class."""
    def __init__(self, classname):
        self.classname = classname
    def __repr__(self):
        return '<%s to "%s">'%(self.__class__, self.classname)

class Multilink:
    """An object designating a Multilink property that links
       to nodes in a specified class.
    """
    def __init__(self, classname):
        self.classname = classname
    def __repr__(self):
        return '<%s to "%s">'%(self.__class__, self.classname)

class DatabaseError(ValueError):
    pass


#
# the base Database class
#
class Database:
    '''A database for storing records containing flexible data types.

This class defines a hyperdatabase storage layer, which the Classes use to
store their data.


Transactions
------------
The Database should support transactions through the commit() and
rollback() methods. All other Database methods should be transaction-aware,
using data from the current transaction before looking up the database.

An implementation must provide an override for the get() method so that the
in-database value is returned in preference to the in-transaction value.
This is necessary to determine if any values have changed during a
transaction.

'''

    # flag to set on retired entries
    RETIRED_FLAG = '__hyperdb_retired'

    def __init__(self, storagelocator, journaltag=None):
        """Open a hyperdatabase given a specifier to some storage.

        The meaning of 'storagelocator' depends on the particular
        implementation of the hyperdatabase.  It could be a file name,
        a directory path, a socket descriptor for a connection to a
        database over the network, etc.

        The 'journaltag' is a token that will be attached to the journal
        entries for any edits done on the database.  If 'journaltag' is
        None, the database is opened in read-only mode: the Class.create(),
        Class.set(), and Class.retire() methods are disabled.
        """
        raise NotImplementedError

    def __getattr__(self, classname):
        """A convenient way of calling self.getclass(classname)."""
        raise NotImplementedError

    def addclass(self, cl):
        '''Add a Class to the hyperdatabase.
        '''
        raise NotImplementedError

    def getclasses(self):
        """Return a list of the names of all existing classes."""
        raise NotImplementedError

    def getclass(self, classname):
        """Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        """
        raise NotImplementedError

    def clear(self):
        '''Delete all database contents.
        '''
        raise NotImplementedError

    def getclassdb(self, classname, mode='r'):
        '''Obtain a connection to the class db that will be used for
           multiple actions.
        '''
        raise NotImplementedError

    def addnode(self, classname, nodeid, node):
        '''Add the specified node to its class's db.
        '''
        raise NotImplementedError

    def setnode(self, classname, nodeid, node):
        '''Change the specified node.
        '''
        raise NotImplementedError

    def getnode(self, classname, nodeid, db=None, cache=1):
        '''Get a node from the database.
        '''
        raise NotImplementedError

    def hasnode(self, classname, nodeid, db=None):
        '''Determine if the database has a given node.
        '''
        raise NotImplementedError

    def countnodes(self, classname, db=None):
        '''Count the number of nodes that exist for a particular Class.
        '''
        raise NotImplementedError

    def getnodeids(self, classname, db=None):
        '''Retrieve all the ids of the nodes for a particular Class.
        '''
        raise NotImplementedError

    def storefile(self, classname, nodeid, property, content):
        '''Store the content of the file in the database.
        
           The property may be None, in which case the filename does not
           indicate which property is being saved.
        '''
        raise NotImplementedError

    def getfile(self, classname, nodeid, property):
        '''Store the content of the file in the database.
        '''
        raise NotImplementedError

    def addjournal(self, classname, nodeid, action, params):
        ''' Journal the Action
        'action' may be:

            'create' or 'set' -- 'params' is a dictionary of property values
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retire' -- 'params' is None
        '''
        raise NotImplementedError

    def getjournal(self, classname, nodeid):
        ''' get the journal for id
        '''
        raise NotImplementedError

    def commit(self):
        ''' Commit the current transactions.

        Save all data changed since the database was opened or since the
        last commit() or rollback().
        '''
        raise NotImplementedError

    def rollback(self):
        ''' Reverse all actions from the current transaction.

        Undo all the changes made since the database was opened or the last
        commit() or rollback() was performed.
        '''
        raise NotImplementedError

_marker = []
#
# The base Class class
#
class Class:
    """The handle to a particular class of nodes in a hyperdatabase."""

    def __init__(self, db, classname, **properties):
        """Create a new class with a given name and property specification.

        'classname' must not collide with the name of an existing class,
        or a ValueError is raised.  The keyword arguments in 'properties'
        must map names to property objects, or a TypeError is raised.
        """
        self.classname = classname
        self.properties = properties
        self.db = weakref.proxy(db)       # use a weak ref to avoid circularity
        self.key = ''

        # do the db-related init stuff
        db.addclass(self)

    def __repr__(self):
        return '<hypderdb.Class "%s">'%self.classname

    # Editing nodes:

    def create(self, **propvalues):
        """Create a new node of this class and return its id.

        The keyword arguments in 'propvalues' map property names to values.

        The values of arguments must be acceptable for the types of their
        corresponding properties or a TypeError is raised.
        
        If this class has a key property, it must be present and its value
        must not collide with other key strings or a ValueError is raised.
        
        Any other properties on this class that are missing from the
        'propvalues' dictionary are set to None.
        
        If an id in a link or multilink property does not refer to a valid
        node, an IndexError is raised.
        """
        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'

        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'

        # new node's id
        newid = str(self.count() + 1)

        # validate propvalues
        num_re = re.compile('^\d+$')
        for key, value in propvalues.items():
            if key == self.key:
                try:
                    self.lookup(value)
                except KeyError:
                    pass
                else:
                    raise ValueError, 'node with key "%s" exists'%value

            # try to handle this property
            try:
                prop = self.properties[key]
            except KeyError:
                raise KeyError, '"%s" has no property "%s"'%(self.classname,
                    key)

            if isinstance(prop, Link):
                if type(value) != type(''):
                    raise ValueError, 'link value must be String'
                link_class = self.properties[key].classname
                # if it isn't a number, it's a key
                if not num_re.match(value):
                    try:
                        value = self.db.classes[link_class].lookup(value)
                    except (TypeError, KeyError):
                        raise IndexError, 'new property "%s": %s not a %s'%(
                            key, value, link_class)
                elif not self.db.hasnode(link_class, value):
                    raise IndexError, '%s has no node %s'%(link_class, value)

                # save off the value
                propvalues[key] = value

                # register the link with the newly linked node
                self.db.addjournal(link_class, value, 'link',
                    (self.classname, newid, key))

            elif isinstance(prop, Multilink):
                if type(value) != type([]):
                    raise TypeError, 'new property "%s" not a list of ids'%key
                link_class = self.properties[key].classname
                l = []
                for entry in value:
                    if type(entry) != type(''):
                        raise ValueError, 'link value must be String'
                    # if it isn't a number, it's a key
                    if not num_re.match(entry):
                        try:
                            entry = self.db.classes[link_class].lookup(entry)
                        except (TypeError, KeyError):
                            raise IndexError, 'new property "%s": %s not a %s'%(
                                key, entry, self.properties[key].classname)
                    l.append(entry)
                value = l
                propvalues[key] = value

                # handle additions
                for id in value:
                    if not self.db.hasnode(link_class, id):
                        raise IndexError, '%s has no node %s'%(link_class, id)
                    # register the link with the newly linked node
                    self.db.addjournal(link_class, id, 'link',
                        (self.classname, newid, key))

            elif isinstance(prop, String):
                if type(value) != type(''):
                    raise TypeError, 'new property "%s" not a string'%key

            elif isinstance(prop, Password):
                if not isinstance(value, password.Password):
                    raise TypeError, 'new property "%s" not a Password'%key

            elif isinstance(prop, Date):
                if not isinstance(value, date.Date):
                    raise TypeError, 'new property "%s" not a Date'%key

            elif isinstance(prop, Interval):
                if not isinstance(value, date.Interval):
                    raise TypeError, 'new property "%s" not an Interval'%key

        # make sure there's data where there needs to be
        for key, prop in self.properties.items():
            if propvalues.has_key(key):
                continue
            if key == self.key:
                raise ValueError, 'key property "%s" is required'%key
            if isinstance(prop, Multilink):
                propvalues[key] = []
            else:
                propvalues[key] = None

        # convert all data to strings
        for key, prop in self.properties.items():
            if isinstance(prop, Date):
                propvalues[key] = propvalues[key].get_tuple()
            elif isinstance(prop, Interval):
                propvalues[key] = propvalues[key].get_tuple()
            elif isinstance(prop, Password):
                propvalues[key] = str(propvalues[key])

        # done
        self.db.addnode(self.classname, newid, propvalues)
        self.db.addjournal(self.classname, newid, 'create', propvalues)
        return newid

    def get(self, nodeid, propname, default=_marker, cache=1):
        """Get the value of a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.  'propname' must be the name of a property
        of this class or a KeyError is raised.

        'cache' indicates whether the transaction cache should be queried
        for the node. If the node has been modified and you need to
        determine what its values prior to modification are, you need to
        set cache=0.
        """
        if propname == 'id':
            return nodeid

        # get the node's dict
        d = self.db.getnode(self.classname, nodeid, cache=cache)
        if not d.has_key(propname) and default is not _marker:
            return default

        # get the value
        prop = self.properties[propname]

        # possibly convert the marshalled data to instances
        if isinstance(prop, Date):
            return date.Date(d[propname])
        elif isinstance(prop, Interval):
            return date.Interval(d[propname])
        elif isinstance(prop, Password):
            p = password.Password()
            p.unpack(d[propname])
            return p

        return d[propname]

    # XXX not in spec
    def getnode(self, nodeid, cache=1):
        ''' Return a convenience wrapper for the node.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.

        'cache' indicates whether the transaction cache should be queried
        for the node. If the node has been modified and you need to
        determine what its values prior to modification are, you need to
        set cache=0.
        '''
        return Node(self, nodeid, cache=cache)

    def set(self, nodeid, **propvalues):
        """Modify a property on an existing node of this class.
        
        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.

        Each key in 'propvalues' must be the name of a property of this
        class or a KeyError is raised.

        All values in 'propvalues' must be acceptable types for their
        corresponding properties or a TypeError is raised.

        If the value of the key property is set, it must not collide with
        other key strings or a ValueError is raised.

        If the value of a Link or Multilink property contains an invalid
        node id, a ValueError is raised.
        """
        if not propvalues:
            return

        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'

        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'

        node = self.db.getnode(self.classname, nodeid)
        if node.has_key(self.db.RETIRED_FLAG):
            raise IndexError
        num_re = re.compile('^\d+$')
        for key, value in propvalues.items():
            # check to make sure we're not duplicating an existing key
            if key == self.key and node[key] != value:
                try:
                    self.lookup(value)
                except KeyError:
                    pass
                else:
                    raise ValueError, 'node with key "%s" exists'%value

            # this will raise the KeyError if the property isn't valid
            # ... we don't use getprops() here because we only care about
            # the writeable properties.
            prop = self.properties[key]

            if isinstance(prop, Link):
                link_class = self.properties[key].classname
                # if it isn't a number, it's a key
                if type(value) != type(''):
                    raise ValueError, 'link value must be String'
                if not num_re.match(value):
                    try:
                        value = self.db.classes[link_class].lookup(value)
                    except (TypeError, KeyError):
                        raise IndexError, 'new property "%s": %s not a %s'%(
                            key, value, self.properties[key].classname)

                if not self.db.hasnode(link_class, value):
                    raise IndexError, '%s has no node %s'%(link_class, value)

                # register the unlink with the old linked node
                if node[key] is not None:
                    self.db.addjournal(link_class, node[key], 'unlink',
                        (self.classname, nodeid, key))

                # register the link with the newly linked node
                if value is not None:
                    self.db.addjournal(link_class, value, 'link',
                        (self.classname, nodeid, key))

            elif isinstance(prop, Multilink):
                if type(value) != type([]):
                    raise TypeError, 'new property "%s" not a list of ids'%key
                link_class = self.properties[key].classname
                l = []
                for entry in value:
                    # if it isn't a number, it's a key
                    if type(entry) != type(''):
                        raise ValueError, 'link value must be String'
                    if not num_re.match(entry):
                        try:
                            entry = self.db.classes[link_class].lookup(entry)
                        except (TypeError, KeyError):
                            raise IndexError, 'new property "%s": %s not a %s'%(
                                key, entry, self.properties[key].classname)
                    l.append(entry)
                value = l
                propvalues[key] = value

                #handle removals
                l = node[key]
                for id in l[:]:
                    if id in value:
                        continue
                    # register the unlink with the old linked node
                    self.db.addjournal(link_class, id, 'unlink',
                        (self.classname, nodeid, key))
                    l.remove(id)

                # handle additions
                for id in value:
                    if not self.db.hasnode(link_class, id):
                        raise IndexError, '%s has no node %s'%(link_class, id)
                    if id in l:
                        continue
                    # register the link with the newly linked node
                    self.db.addjournal(link_class, id, 'link',
                        (self.classname, nodeid, key))
                    l.append(id)

            elif isinstance(prop, String):
                if value is not None and type(value) != type(''):
                    raise TypeError, 'new property "%s" not a string'%key

            elif isinstance(prop, Password):
                if not isinstance(value, password.Password):
                    raise TypeError, 'new property "%s" not a Password'% key
                propvalues[key] = value = str(value)

            elif isinstance(prop, Date):
                if not isinstance(value, date.Date):
                    raise TypeError, 'new property "%s" not a Date'% key
                propvalues[key] = value = value.get_tuple()

            elif isinstance(prop, Interval):
                if not isinstance(value, date.Interval):
                    raise TypeError, 'new property "%s" not an Interval'% key
                propvalues[key] = value = value.get_tuple()

            node[key] = value

        self.db.setnode(self.classname, nodeid, node)
        self.db.addjournal(self.classname, nodeid, 'set', propvalues)

    def retire(self, nodeid):
        """Retire a node.
        
        The properties on the node remain available from the get() method,
        and the node's id is never reused.
        
        Retired nodes are not returned by the find(), list(), or lookup()
        methods, and other nodes may reuse the values of their key properties.
        """
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'
        node = self.db.getnode(self.classname, nodeid)
        node[self.db.RETIRED_FLAG] = 1
        self.db.setnode(self.classname, nodeid, node)
        self.db.addjournal(self.classname, nodeid, 'retired', None)

    def history(self, nodeid):
        """Retrieve the journal of edits on a particular node.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.

        The returned list contains tuples of the form

            (date, tag, action, params)

        'date' is a Timestamp object specifying the time of the change and
        'tag' is the journaltag specified when the database was opened.
        """
        return self.db.getjournal(self.classname, nodeid)

    # Locating nodes:

    def setkey(self, propname):
        """Select a String property of this class to be the key property.

        'propname' must be the name of a String property of this class or
        None, or a TypeError is raised.  The values of the key property on
        all existing nodes must be unique or a ValueError is raised.
        """
        # TODO: validate that the property is a String!
        self.key = propname

    def getkey(self):
        """Return the name of the key property for this class or None."""
        return self.key

    def labelprop(self, default_to_id=0):
        ''' Return the property name for a label for the given node.

        This method attempts to generate a consistent label for the node.
        It tries the following in order:
            1. key property
            2. "name" property
            3. "title" property
            4. first property from the sorted property name list
        '''
        k = self.getkey()
        if  k:
            return k
        props = self.getprops()
        if props.has_key('name'):
            return 'name'
        elif props.has_key('title'):
            return 'title'
        if default_to_id:
            return 'id'
        props = props.keys()
        props.sort()
        return props[0]

    # TODO: set up a separate index db file for this? profile?
    def lookup(self, keyvalue):
        """Locate a particular node by its key property and return its id.

        If this class has no key property, a TypeError is raised.  If the
        'keyvalue' matches one of the values for the key property among
        the nodes in this class, the matching node's id is returned;
        otherwise a KeyError is raised.
        """
        cldb = self.db.getclassdb(self.classname)
        for nodeid in self.db.getnodeids(self.classname, cldb):
            node = self.db.getnode(self.classname, nodeid, cldb)
            if node.has_key(self.db.RETIRED_FLAG):
                continue
            if node[self.key] == keyvalue:
                return nodeid
        raise KeyError, keyvalue

    # XXX: change from spec - allows multiple props to match
    def find(self, **propspec):
        """Get the ids of nodes in this class which link to a given node.

        'propspec' consists of keyword args propname=nodeid   
          'propname' must be the name of a property in this class, or a
            KeyError is raised.  That property must be a Link or Multilink
            property, or a TypeError is raised.

          'nodeid' must be the id of an existing node in the class linked
            to by the given property, or an IndexError is raised.
        """
        propspec = propspec.items()
        for propname, nodeid in propspec:
            # check the prop is OK
            prop = self.properties[propname]
            if not isinstance(prop, Link) and not isinstance(prop, Multilink):
                raise TypeError, "'%s' not a Link/Multilink property"%propname
            if not self.db.hasnode(prop.classname, nodeid):
                raise ValueError, '%s has no node %s'%(prop.classname, nodeid)

        # ok, now do the find
        cldb = self.db.getclassdb(self.classname)
        l = []
        for id in self.db.getnodeids(self.classname, cldb):
            node = self.db.getnode(self.classname, id, cldb)
            if node.has_key(self.db.RETIRED_FLAG):
                continue
            for propname, nodeid in propspec:
                property = node[propname]
                if isinstance(prop, Link) and nodeid == property:
                    l.append(id)
                elif isinstance(prop, Multilink) and nodeid in property:
                    l.append(id)
        return l

    def stringFind(self, **requirements):
        """Locate a particular node by matching a set of its String
        properties in a caseless search.

        If the property is not a String property, a TypeError is raised.
        
        The return is a list of the id of all nodes that match.
        """
        for propname in requirements.keys():
            prop = self.properties[propname]
            if isinstance(not prop, String):
                raise TypeError, "'%s' not a String property"%propname
            requirements[propname] = requirements[propname].lower()
        l = []
        cldb = self.db.getclassdb(self.classname)
        for nodeid in self.db.getnodeids(self.classname, cldb):
            node = self.db.getnode(self.classname, nodeid, cldb)
            if node.has_key(self.db.RETIRED_FLAG):
                continue
            for key, value in requirements.items():
                if node[key] and node[key].lower() != value:
                    break
            else:
                l.append(nodeid)
        return l

    def list(self):
        """Return a list of the ids of the active nodes in this class."""
        l = []
        cn = self.classname
        cldb = self.db.getclassdb(cn)
        for nodeid in self.db.getnodeids(cn, cldb):
            node = self.db.getnode(cn, nodeid, cldb)
            if node.has_key(self.db.RETIRED_FLAG):
                continue
            l.append(nodeid)
        l.sort()
        return l

    # XXX not in spec
    def filter(self, filterspec, sort, group, num_re = re.compile('^\d+$')):
        ''' Return a list of the ids of the active nodes in this class that
            match the 'filter' spec, sorted by the group spec and then the
            sort spec
        '''
        cn = self.classname

        # optimise filterspec
        l = []
        props = self.getprops()
        for k, v in filterspec.items():
            propclass = props[k]
            if isinstance(propclass, Link):
                if type(v) is not type([]):
                    v = [v]
                # replace key values with node ids
                u = []
                link_class =  self.db.classes[propclass.classname]
                for entry in v:
                    if entry == '-1': entry = None
                    elif not num_re.match(entry):
                        try:
                            entry = link_class.lookup(entry)
                        except (TypeError,KeyError):
                            raise ValueError, 'property "%s": %s not a %s'%(
                                k, entry, self.properties[k].classname)
                    u.append(entry)

                l.append((0, k, u))
            elif isinstance(propclass, Multilink):
                if type(v) is not type([]):
                    v = [v]
                # replace key values with node ids
                u = []
                link_class =  self.db.classes[propclass.classname]
                for entry in v:
                    if not num_re.match(entry):
                        try:
                            entry = link_class.lookup(entry)
                        except (TypeError,KeyError):
                            raise ValueError, 'new property "%s": %s not a %s'%(
                                k, entry, self.properties[k].classname)
                    u.append(entry)
                l.append((1, k, u))
            elif isinstance(propclass, String):
                # simple glob searching
                v = re.sub(r'([\|\{\}\\\.\+\[\]\(\)])', r'\\\1', v)
                v = v.replace('?', '.')
                v = v.replace('*', '.*?')
                l.append((2, k, re.compile(v, re.I)))
            else:
                l.append((6, k, v))
        filterspec = l

        # now, find all the nodes that are active and pass filtering
        l = []
        cldb = self.db.getclassdb(cn)
        for nodeid in self.db.getnodeids(cn, cldb):
            node = self.db.getnode(cn, nodeid, cldb)
            if node.has_key(self.db.RETIRED_FLAG):
                continue
            # apply filter
            for t, k, v in filterspec:
                # this node doesn't have this property, so reject it
                if not node.has_key(k): break

                if t == 0 and node[k] not in v:
                    # link - if this node'd property doesn't appear in the
                    # filterspec's nodeid list, skip it
                    break
                elif t == 1:
                    # multilink - if any of the nodeids required by the
                    # filterspec aren't in this node's property, then skip
                    # it
                    for value in v:
                        if value not in node[k]:
                            break
                    else:
                        continue
                    break
                elif t == 2 and not v.search(node[k]):
                    # RE search
                    break
                elif t == 6 and node[k] != v:
                    # straight value comparison for the other types
                    break
            else:
                l.append((nodeid, node))
        l.sort()

        # optimise sort
        m = []
        for entry in sort:
            if entry[0] != '-':
                m.append(('+', entry))
            else:
                m.append((entry[0], entry[1:]))
        sort = m

        # optimise group
        m = []
        for entry in group:
            if entry[0] != '-':
                m.append(('+', entry))
            else:
                m.append((entry[0], entry[1:]))
        group = m
        # now, sort the result
        def sortfun(a, b, sort=sort, group=group, properties=self.getprops(),
                db = self.db, cl=self):
            a_id, an = a
            b_id, bn = b
            # sort by group and then sort
            for list in group, sort:
                for dir, prop in list:
                    # sorting is class-specific
                    propclass = properties[prop]

                    # handle the properties that might be "faked"
                    # also, handle possible missing properties
                    try:
                        if not an.has_key(prop):
                            an[prop] = cl.get(a_id, prop)
                        av = an[prop]
                    except KeyError:
                        # the node doesn't have a value for this property
                        if isinstance(propclass, Multilink): av = []
                        else: av = ''
                    try:
                        if not bn.has_key(prop):
                            bn[prop] = cl.get(b_id, prop)
                        bv = bn[prop]
                    except KeyError:
                        # the node doesn't have a value for this property
                        if isinstance(propclass, Multilink): bv = []
                        else: bv = ''

                    # String and Date values are sorted in the natural way
                    if isinstance(propclass, String):
                        # clean up the strings
                        if av and av[0] in string.uppercase:
                            av = an[prop] = av.lower()
                        if bv and bv[0] in string.uppercase:
                            bv = bn[prop] = bv.lower()
                    if (isinstance(propclass, String) or
                            isinstance(propclass, Date)):
                        # it might be a string that's really an integer
                        try:
                            av = int(av)
                            bv = int(bv)
                        except:
                            pass
                        if dir == '+':
                            r = cmp(av, bv)
                            if r != 0: return r
                        elif dir == '-':
                            r = cmp(bv, av)
                            if r != 0: return r

                    # Link properties are sorted according to the value of
                    # the "order" property on the linked nodes if it is
                    # present; or otherwise on the key string of the linked
                    # nodes; or finally on  the node ids.
                    elif isinstance(propclass, Link):
                        link = db.classes[propclass.classname]
                        if av is None and bv is not None: return -1
                        if av is not None and bv is None: return 1
                        if av is None and bv is None: continue
                        if link.getprops().has_key('order'):
                            if dir == '+':
                                r = cmp(link.get(av, 'order'),
                                    link.get(bv, 'order'))
                                if r != 0: return r
                            elif dir == '-':
                                r = cmp(link.get(bv, 'order'),
                                    link.get(av, 'order'))
                                if r != 0: return r
                        elif link.getkey():
                            key = link.getkey()
                            if dir == '+':
                                r = cmp(link.get(av, key), link.get(bv, key))
                                if r != 0: return r
                            elif dir == '-':
                                r = cmp(link.get(bv, key), link.get(av, key))
                                if r != 0: return r
                        else:
                            if dir == '+':
                                r = cmp(av, bv)
                                if r != 0: return r
                            elif dir == '-':
                                r = cmp(bv, av)
                                if r != 0: return r

                    # Multilink properties are sorted according to how many
                    # links are present.
                    elif isinstance(propclass, Multilink):
                        if dir == '+':
                            r = cmp(len(av), len(bv))
                            if r != 0: return r
                        elif dir == '-':
                            r = cmp(len(bv), len(av))
                            if r != 0: return r
                # end for dir, prop in list:
            # end for list in sort, group:
            # if all else fails, compare the ids
            return cmp(a[0], b[0])

        l.sort(sortfun)
        return [i[0] for i in l]

    def count(self):
        """Get the number of nodes in this class.

        If the returned integer is 'numnodes', the ids of all the nodes
        in this class run from 1 to numnodes, and numnodes+1 will be the
        id of the next node to be created in this class.
        """
        return self.db.countnodes(self.classname)

    # Manipulating properties:

    def getprops(self, protected=1):
        """Return a dictionary mapping property names to property objects.
           If the "protected" flag is true, we include protected properties -
           those which may not be modified."""
        d = self.properties.copy()
        if protected:
            d['id'] = String()
        return d

    def addprop(self, **properties):
        """Add properties to this class.

        The keyword arguments in 'properties' must map names to property
        objects, or a TypeError is raised.  None of the keys in 'properties'
        may collide with the names of existing properties, or a ValueError
        is raised before any properties have been added.
        """
        for key in properties.keys():
            if self.properties.has_key(key):
                raise ValueError, key
        self.properties.update(properties)


# XXX not in spec
class Node:
    ''' A convenience wrapper for the given node
    '''
    def __init__(self, cl, nodeid, cache=1):
        self.__dict__['cl'] = cl
        self.__dict__['nodeid'] = nodeid
        self.__dict__['cache'] = cache
    def keys(self, protected=1):
        return self.cl.getprops(protected=protected).keys()
    def values(self, protected=1):
        l = []
        for name in self.cl.getprops(protected=protected).keys():
            l.append(self.cl.get(self.nodeid, name, cache=self.cache))
        return l
    def items(self, protected=1):
        l = []
        for name in self.cl.getprops(protected=protected).keys():
            l.append((name, self.cl.get(self.nodeid, name, cache=self.cache)))
        return l
    def has_key(self, name):
        return self.cl.getprops().has_key(name)
    def __getattr__(self, name):
        if self.__dict__.has_key(name):
            return self.__dict__[name]
        try:
            return self.cl.get(self.nodeid, name, cache=self.cache)
        except KeyError, value:
            # we trap this but re-raise it as AttributeError - all other
            # exceptions should pass through untrapped
            pass
        # nope, no such attribute
        raise AttributeError, str(value)
    def __getitem__(self, name):
        return self.cl.get(self.nodeid, name, cache=self.cache)
    def __setattr__(self, name, value):
        try:
            return self.cl.set(self.nodeid, **{name: value})
        except KeyError, value:
            raise AttributeError, str(value)
    def __setitem__(self, name, value):
        self.cl.set(self.nodeid, **{name: value})
    def history(self):
        return self.cl.history(self.nodeid)
    def retire(self):
        return self.cl.retire(self.nodeid)


def Choice(name, *options):
    cl = Class(db, name, name=hyperdb.String(), order=hyperdb.String())
    for i in range(len(options)):
        cl.create(name=option[i], order=i)
    return hyperdb.Link(name)

#
# $Log: not supported by cvs2svn $
# Revision 1.45  2002/01/02 04:18:17  richard
# hyperdb docstrings
#
# Revision 1.44  2002/01/02 02:31:38  richard
# Sorry for the huge checkin message - I was only intending to implement #496356
# but I found a number of places where things had been broken by transactions:
#  . modified ROUNDUPDBSENDMAILDEBUG to be SENDMAILDEBUG and hold a filename
#    for _all_ roundup-generated smtp messages to be sent to.
#  . the transaction cache had broken the roundupdb.Class set() reactors
#  . newly-created author users in the mailgw weren't being committed to the db
#
# Stuff that made it into CHANGES.txt (ie. the stuff I was actually working
# on when I found that stuff :):
#  . #496356 ] Use threading in messages
#  . detectors were being registered multiple times
#  . added tests for mailgw
#  . much better attaching of erroneous messages in the mail gateway
#
# Revision 1.43  2001/12/20 06:13:24  rochecompaan
# Bugs fixed:
#   . Exception handling in hyperdb for strings-that-look-like numbers got
#     lost somewhere
#   . Internet Explorer submits full path for filename - we now strip away
#     the path
# Features added:
#   . Link and multilink properties are now displayed sorted in the cgi
#     interface
#
# Revision 1.42  2001/12/16 10:53:37  richard
# take a copy of the node dict so that the subsequent set
# operation doesn't modify the oldvalues structure
#
# Revision 1.41  2001/12/15 23:47:47  richard
# Cleaned up some bare except statements
#
# Revision 1.40  2001/12/14 23:42:57  richard
# yuck, a gdbm instance tests false :(
# I've left the debugging code in - it should be removed one day if we're ever
# _really_ anal about performace :)
#
# Revision 1.39  2001/12/02 05:06:16  richard
# . We now use weakrefs in the Classes to keep the database reference, so
#   the close() method on the database is no longer needed.
#   I bumped the minimum python requirement up to 2.1 accordingly.
# . #487480 ] roundup-server
# . #487476 ] INSTALL.txt
#
# I also cleaned up the change message / post-edit stuff in the cgi client.
# There's now a clearly marked "TODO: append the change note" where I believe
# the change note should be added there. The "changes" list will obviously
# have to be modified to be a dict of the changes, or somesuch.
#
# More testing needed.
#
# Revision 1.38  2001/12/01 07:17:50  richard
# . We now have basic transaction support! Information is only written to
#   the database when the commit() method is called. Only the anydbm
#   backend is modified in this way - neither of the bsddb backends have been.
#   The mail, admin and cgi interfaces all use commit (except the admin tool
#   doesn't have a commit command, so interactive users can't commit...)
# . Fixed login/registration forwarding the user to the right page (or not,
#   on a failure)
#
# Revision 1.37  2001/11/28 21:55:35  richard
#  . login_action and newuser_action return values were being ignored
#  . Woohoo! Found that bloody re-login bug that was killing the mail
#    gateway.
#  (also a minor cleanup in hyperdb)
#
# Revision 1.36  2001/11/27 03:16:09  richard
# Another place that wasn't handling missing properties.
#
# Revision 1.35  2001/11/22 15:46:42  jhermann
# Added module docstrings to all modules.
#
# Revision 1.34  2001/11/21 04:04:43  richard
# *sigh* more missing value handling
#
# Revision 1.33  2001/11/21 03:40:54  richard
# more new property handling
#
# Revision 1.32  2001/11/21 03:11:28  richard
# Better handling of new properties.
#
# Revision 1.31  2001/11/12 22:01:06  richard
# Fixed issues with nosy reaction and author copies.
#
# Revision 1.30  2001/11/09 10:11:08  richard
#  . roundup-admin now handles all hyperdb exceptions
#
# Revision 1.29  2001/10/27 00:17:41  richard
# Made Class.stringFind() do caseless matching.
#
# Revision 1.28  2001/10/21 04:44:50  richard
# bug #473124: UI inconsistency with Link fields.
#    This also prompted me to fix a fairly long-standing usability issue -
#    that of being able to turn off certain filters.
#
# Revision 1.27  2001/10/20 23:44:27  richard
# Hyperdatabase sorts strings-that-look-like-numbers as numbers now.
#
# Revision 1.26  2001/10/16 03:48:01  richard
# admin tool now complains if a "find" is attempted with a non-link property.
#
# Revision 1.25  2001/10/11 00:17:51  richard
# Reverted a change in hyperdb so the default value for missing property
# values in a create() is None and not '' (the empty string.) This obviously
# breaks CSV import/export - the string 'None' will be created in an
# export/import operation.
#
# Revision 1.24  2001/10/10 03:54:57  richard
# Added database importing and exporting through CSV files.
# Uses the csv module from object-craft for exporting if it's available.
# Requires the csv module for importing.
#
# Revision 1.23  2001/10/09 23:58:10  richard
# Moved the data stringification up into the hyperdb.Class class' get, set
# and create methods. This means that the data is also stringified for the
# journal call, and removes duplication of code from the backends. The
# backend code now only sees strings.
#
# Revision 1.22  2001/10/09 07:25:59  richard
# Added the Password property type. See "pydoc roundup.password" for
# implementation details. Have updated some of the documentation too.
#
# Revision 1.21  2001/10/05 02:23:24  richard
#  . roundup-admin create now prompts for property info if none is supplied
#    on the command-line.
#  . hyperdb Class getprops() method may now return only the mutable
#    properties.
#  . Login now uses cookies, which makes it a whole lot more flexible. We can
#    now support anonymous user access (read-only, unless there's an
#    "anonymous" user, in which case write access is permitted). Login
#    handling has been moved into cgi_client.Client.main()
#  . The "extended" schema is now the default in roundup init.
#  . The schemas have had their page headings modified to cope with the new
#    login handling. Existing installations should copy the interfaces.py
#    file from the roundup lib directory to their instance home.
#  . Incorrectly had a Bizar Software copyright on the cgitb.py module from
#    Ping - has been removed.
#  . Fixed a whole bunch of places in the CGI interface where we should have
#    been returning Not Found instead of throwing an exception.
#  . Fixed a deviation from the spec: trying to modify the 'id' property of
#    an item now throws an exception.
#
# Revision 1.20  2001/10/04 02:12:42  richard
# Added nicer command-line item adding: passing no arguments will enter an
# interactive more which asks for each property in turn. While I was at it, I
# fixed an implementation problem WRT the spec - I wasn't raising a
# ValueError if the key property was missing from a create(). Also added a
# protected=boolean argument to getprops() so we can list only the mutable
# properties (defaults to yes, which lists the immutables).
#
# Revision 1.19  2001/08/29 04:47:18  richard
# Fixed CGI client change messages so they actually include the properties
# changed (again).
#
# Revision 1.18  2001/08/16 07:34:59  richard
# better CGI text searching - but hidden filter fields are disappearing...
#
# Revision 1.17  2001/08/16 06:59:58  richard
# all searches use re now - and they're all case insensitive
#
# Revision 1.16  2001/08/15 23:43:18  richard
# Fixed some isFooTypes that I missed.
# Refactored some code in the CGI code.
#
# Revision 1.15  2001/08/12 06:32:36  richard
# using isinstance(blah, Foo) now instead of isFooType
#
# Revision 1.14  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.13  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.12  2001/08/02 06:38:17  richard
# Roundupdb now appends "mailing list" information to its messages which
# include the e-mail address and web interface address. Templates may
# override this in their db classes to include specific information (support
# instructions, etc).
#
# Revision 1.11  2001/08/01 04:24:21  richard
# mailgw was assuming certain properties existed on the issues being created.
#
# Revision 1.10  2001/07/30 02:38:31  richard
# get() now has a default arg - for migration only.
#
# Revision 1.9  2001/07/29 09:28:23  richard
# Fixed sorting by clicking on column headings.
#
# Revision 1.8  2001/07/29 08:27:40  richard
# Fixed handling of passed-in values in form elements (ie. during a
# drill-down)
#
# Revision 1.7  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.6  2001/07/29 05:36:14  richard
# Cleanup of the link label generation.
#
# Revision 1.5  2001/07/29 04:05:37  richard
# Added the fabricated property "id".
#
# Revision 1.4  2001/07/27 06:25:35  richard
# Fixed some of the exceptions so they're the right type.
# Removed the str()-ification of node ids so we don't mask oopsy errors any
# more.
#
# Revision 1.3  2001/07/27 05:17:14  richard
# just some comments
#
# Revision 1.2  2001/07/22 12:09:32  richard
# Final commit of Grande Splite
#
# Revision 1.1  2001/07/22 11:58:35  richard
# More Grande Splite
#
#
# vim: set filetype=python ts=4 sw=4 et si
