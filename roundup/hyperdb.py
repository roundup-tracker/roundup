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
# $Id: hyperdb.py,v 1.83 2002-10-03 06:56:29 richard Exp $

"""
Hyperdatabase implementation, especially field types.
"""

# standard python modules
import sys, os, time, re

# roundup modules
import date, password

# configure up the DEBUG and TRACE captures
class Sink:
    def write(self, content):
        pass
DEBUG = os.environ.get('HYPERDBDEBUG', '')
if DEBUG and __debug__:
    if DEBUG == 'stdout':
        DEBUG = sys.stdout
    else:
        DEBUG = open(DEBUG, 'a')
else:
    DEBUG = Sink()
TRACE = os.environ.get('HYPERDBTRACE', '')
if TRACE and __debug__:
    if TRACE == 'stdout':
        TRACE = sys.stdout
    else:
        TRACE = open(TRACE, 'w')
else:
    TRACE = Sink()
def traceMark():
    print >>TRACE, '**MARK', time.ctime()
del Sink

#
# Types
#
class String:
    """An object designating a String property."""
    def __init__(self, indexme='no'):
        self.indexme = indexme == 'yes'
    def __repr__(self):
        ' more useful for dumps '
        return '<%s>'%self.__class__

class Password:
    """An object designating a Password property."""
    def __repr__(self):
        ' more useful for dumps '
        return '<%s>'%self.__class__

class Date:
    """An object designating a Date property."""
    def __repr__(self):
        ' more useful for dumps '
        return '<%s>'%self.__class__

class Interval:
    """An object designating an Interval property."""
    def __repr__(self):
        ' more useful for dumps '
        return '<%s>'%self.__class__

class Link:
    """An object designating a Link property that links to a
       node in a specified class."""
    def __init__(self, classname, do_journal='yes'):
        ''' Default is to not journal link and unlink events
        '''
        self.classname = classname
        self.do_journal = do_journal == 'yes'
    def __repr__(self):
        ' more useful for dumps '
        return '<%s to "%s">'%(self.__class__, self.classname)

class Multilink:
    """An object designating a Multilink property that links
       to nodes in a specified class.

       "classname" indicates the class to link to

       "do_journal" indicates whether the linked-to nodes should have
                    'link' and 'unlink' events placed in their journal
    """
    def __init__(self, classname, do_journal='yes'):
        ''' Default is to not journal link and unlink events
        '''
        self.classname = classname
        self.do_journal = do_journal == 'yes'
    def __repr__(self):
        ' more useful for dumps '
        return '<%s to "%s">'%(self.__class__, self.classname)

class Boolean:
    """An object designating a boolean property"""
    def __repr__(self):
        'more useful for dumps'
        return '<%s>' % self.__class__
    
class Number:
    """An object designating a numeric property"""
    def __repr__(self):
        'more useful for dumps'
        return '<%s>' % self.__class__
#
# Support for splitting designators
#
class DesignatorError(ValueError):
    pass
def splitDesignator(designator, dre=re.compile(r'([^\d]+)(\d+)')):
    ''' Take a foo123 and return ('foo', 123)
    '''
    m = dre.match(designator)
    if m is None:
        raise DesignatorError, '"%s" not a node designator'%designator
    return m.group(1), m.group(2)

#
# the base Database class
#
class DatabaseError(ValueError):
    '''Error to be raised when there is some problem in the database code
    '''
    pass
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


Implementation
--------------

All methods except __repr__ and getnode must be implemented by a
concrete backend Class.

'''

    # flag to set on retired entries
    RETIRED_FLAG = '__hyperdb_retired'

    def __init__(self, config, journaltag=None):
        """Open a hyperdatabase given a specifier to some storage.

        The 'storagelocator' is obtained from config.DATABASE.
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

    def post_init(self):
        """Called once the schema initialisation has finished."""
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

    def serialise(self, classname, node):
        '''Copy the node contents, converting non-marshallable data into
           marshallable data.
        '''
        return node

    def setnode(self, classname, nodeid, node):
        '''Change the specified node.
        '''
        raise NotImplementedError

    def unserialise(self, classname, node):
        '''Decode the marshalled node data
        '''
        return node

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

    def pack(self, pack_before):
        ''' pack the database
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

#
# The base Class class
#
class Class:
    """ The handle to a particular class of nodes in a hyperdatabase.
        
        All methods except __repr__ and getnode must be implemented by a
        concrete backend Class.
    """

    def __init__(self, db, classname, **properties):
        """Create a new class with a given name and property specification.

        'classname' must not collide with the name of an existing class,
        or a ValueError is raised.  The keyword arguments in 'properties'
        must map names to property objects, or a TypeError is raised.
        """
        raise NotImplementedError

    def __repr__(self):
        '''Slightly more useful representation
        '''
        return '<hyperdb.Class "%s">'%self.classname

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
        raise NotImplementedError

    _marker = []
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
        raise NotImplementedError

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
        raise NotImplementedError

    def retire(self, nodeid):
        """Retire a node.
        
        The properties on the node remain available from the get() method,
        and the node's id is never reused.
        
        Retired nodes are not returned by the find(), list(), or lookup()
        methods, and other nodes may reuse the values of their key properties.
        """
        raise NotImplementedError

    def is_retired(self, nodeid):
        '''Return true if the node is rerired
        '''
        raise NotImplementedError

    def destroy(self, nodeid):
        """Destroy a node.
        
        WARNING: this method should never be used except in extremely rare
                 situations where there could never be links to the node being
                 deleted
        WARNING: use retire() instead
        WARNING: the properties of this node will not be available ever again
        WARNING: really, use retire() instead

        Well, I think that's enough warnings. This method exists mostly to
        support the session storage of the cgi interface.

        The node is completely removed from the hyperdb, including all journal
        entries. It will no longer be available, and will generally break code
        if there are any references to the node.
        """

    def history(self, nodeid):
        """Retrieve the journal of edits on a particular node.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.

        The returned list contains tuples of the form

            (date, tag, action, params)

        'date' is a Timestamp object specifying the time of the change and
        'tag' is the journaltag specified when the database was opened.
        """
        raise NotImplementedError

    # Locating nodes:
    def hasnode(self, nodeid):
        '''Determine if the given nodeid actually exists
        '''
        raise NotImplementedError

    def setkey(self, propname):
        """Select a String property of this class to be the key property.

        'propname' must be the name of a String property of this class or
        None, or a TypeError is raised.  The values of the key property on
        all existing nodes must be unique or a ValueError is raised.
        """
        raise NotImplementedError

    def getkey(self):
        """Return the name of the key property for this class or None."""
        raise NotImplementedError

    def labelprop(self, default_to_id=0):
        ''' Return the property name for a label for the given node.

        This method attempts to generate a consistent label for the node.
        It tries the following in order:
            1. key property
            2. "name" property
            3. "title" property
            4. first property from the sorted property name list
        '''
        raise NotImplementedError

    def lookup(self, keyvalue):
        """Locate a particular node by its key property and return its id.

        If this class has no key property, a TypeError is raised.  If the
        'keyvalue' matches one of the values for the key property among
        the nodes in this class, the matching node's id is returned;
        otherwise a KeyError is raised.
        """
        raise NotImplementedError

    def find(self, **propspec):
        """Get the ids of nodes in this class which link to the given nodes.

        'propspec' consists of keyword args propname={nodeid:1,}   
        'propname' must be the name of a property in this class, or a
        KeyError is raised.  That property must be a Link or Multilink
        property, or a TypeError is raised.

        Any node in this class whose 'propname' property links to any of the
        nodeids will be returned. Used by the full text indexing, which knows
        that "foo" occurs in msg1, msg3 and file7, so we have hits on these
        issues:

            db.issue.find(messages={'1':1,'3':1}, files={'7':1})
        """
        raise NotImplementedError

    def filter(self, search_matches, filterspec, sort, group, 
            num_re = re.compile('^\d+$')):
        ''' Return a list of the ids of the active nodes in this class that
            match the 'filter' spec, sorted by the group spec and then the
            sort spec
        '''
        raise NotImplementedError

    def count(self):
        """Get the number of nodes in this class.

        If the returned integer is 'numnodes', the ids of all the nodes
        in this class run from 1 to numnodes, and numnodes+1 will be the
        id of the next node to be created in this class.
        """
        raise NotImplementedError

    # Manipulating properties:
    def getprops(self, protected=1):
        """Return a dictionary mapping property names to property objects.
           If the "protected" flag is true, we include protected properties -
           those which may not be modified.
        """
        raise NotImplementedError

    def addprop(self, **properties):
        """Add properties to this class.

        The keyword arguments in 'properties' must map names to property
        objects, or a TypeError is raised.  None of the keys in 'properties'
        may collide with the names of existing properties, or a ValueError
        is raised before any properties have been added.
        """
        raise NotImplementedError

    def index(self, nodeid):
        '''Add (or refresh) the node to search indexes
        '''
        raise NotImplementedError

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


def Choice(name, db, *options):
    '''Quick helper to create a simple class with choices
    '''
    cl = Class(db, name, name=String(), order=String())
    for i in range(len(options)):
        cl.create(name=options[i], order=i)
    return hyperdb.Link(name)

# vim: set filetype=python ts=4 sw=4 et si
