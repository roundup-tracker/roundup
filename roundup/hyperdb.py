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
# $Id: hyperdb.py,v 1.78 2002-07-21 03:26:37 richard Exp $

__doc__ = """
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
    def __init__(self, classname, do_journal='no'):
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
    def __init__(self, classname, do_journal='no'):
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

    # XXX deviates from spec: storagelocator is obtained from the config
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
        raise NotImplementedError

    def retire(self, nodeid):
        """Retire a node.
        
        The properties on the node remain available from the get() method,
        and the node's id is never reused.
        
        Retired nodes are not returned by the find(), list(), or lookup()
        methods, and other nodes may reuse the values of their key properties.
        """
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

    # XXX: change from spec - allows multiple props to match
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

    # XXX not in spec
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


def Choice(name, db, *options):
    '''Quick helper to create a simple class with choices
    '''
    cl = Class(db, name, name=String(), order=String())
    for i in range(len(options)):
        cl.create(name=options[i], order=i)
    return hyperdb.Link(name)

#
# $Log: not supported by cvs2svn $
# Revision 1.77  2002/07/18 11:27:47  richard
# ws
#
# Revision 1.76  2002/07/18 11:17:30  gmcm
# Add Number and Boolean types to hyperdb.
# Add conversion cases to web, mail & admin interfaces.
# Add storage/serialization cases to back_anydbm & back_metakit.
#
# Revision 1.75  2002/07/14 02:05:53  richard
# . all storage-specific code (ie. backend) is now implemented by the backends
#
# Revision 1.74  2002/07/10 00:24:10  richard
# braino
#
# Revision 1.73  2002/07/10 00:19:48  richard
# Added explicit closing of backend database handles.
#
# Revision 1.72  2002/07/09 21:53:38  gmcm
# Optimize Class.find so that the propspec can contain a set of ids to match.
# This is used by indexer.search so it can do just one find for all the index matches.
# This was already confusing code, but for common terms (lots of index matches),
# it is enormously faster.
#
# Revision 1.71  2002/07/09 03:02:52  richard
# More indexer work:
# - all String properties may now be indexed too. Currently there's a bit of
#   "issue" specific code in the actual searching which needs to be
#   addressed. In a nutshell:
#   + pass 'indexme="yes"' as a String() property initialisation arg, eg:
#         file = FileClass(db, "file", name=String(), type=String(),
#             comment=String(indexme="yes"))
#   + the comment will then be indexed and be searchable, with the results
#     related back to the issue that the file is linked to
# - as a result of this work, the FileClass has a default MIME type that may
#   be overridden in a subclass, or by the use of a "type" property as is
#   done in the default templates.
# - the regeneration of the indexes (if necessary) is done once the schema is
#   set up in the dbinit.
#
# Revision 1.70  2002/06/27 12:06:20  gmcm
# Improve an error message.
#
# Revision 1.69  2002/06/17 23:15:29  richard
# Can debug to stdout now
#
# Revision 1.68  2002/06/11 06:52:03  richard
#  . #564271 ] find() and new properties
#
# Revision 1.67  2002/06/11 05:02:37  richard
#  . #565979 ] code error in hyperdb.Class.find
#
# Revision 1.66  2002/05/25 07:16:24  rochecompaan
# Merged search_indexing-branch with HEAD
#
# Revision 1.65  2002/05/22 04:12:05  richard
#  . applied patch #558876 ] cgi client customization
#    ... with significant additions and modifications ;)
#    - extended handling of ML assignedto to all places it's handled
#    - added more NotFound info
#
# Revision 1.64  2002/05/15 06:21:21  richard
#  . node caching now works, and gives a small boost in performance
#
# As a part of this, I cleaned up the DEBUG output and implemented TRACE
# output (HYPERDBTRACE='file to trace to') with checkpoints at the start of
# CGI requests. Run roundup with python -O to skip all the DEBUG/TRACE stuff
# (using if __debug__ which is compiled out with -O)
#
# Revision 1.63  2002/04/15 23:25:15  richard
# . node ids are now generated from a lockable store - no more race conditions
#
# We're using the portalocker code by Jonathan Feinberg that was contributed
# to the ASPN Python cookbook. This gives us locking across Unix and Windows.
#
# Revision 1.62  2002/04/03 07:05:50  richard
# d'oh! killed retirement of nodes :(
# all better now...
#
# Revision 1.61  2002/04/03 06:11:51  richard
# Fix for old databases that contain properties that don't exist any more.
#
# Revision 1.60  2002/04/03 05:54:31  richard
# Fixed serialisation problem by moving the serialisation step out of the
# hyperdb.Class (get, set) into the hyperdb.Database.
#
# Also fixed htmltemplate after the showid changes I made yesterday.
#
# Unit tests for all of the above written.
#
# Revision 1.59.2.2  2002/04/20 13:23:33  rochecompaan
# We now have a separate search page for nodes.  Search links for
# different classes can be customized in instance_config similar to
# index links.
#
# Revision 1.59.2.1  2002/04/19 19:54:42  rochecompaan
# cgi_client.py
#     removed search link for the time being
#     moved rendering of matches to htmltemplate
# hyperdb.py
#     filtering of nodes on full text search incorporated in filter method
# roundupdb.py
#     added paramater to call of filter method
# roundup_indexer.py
#     added search method to RoundupIndexer class
#
# Revision 1.59  2002/03/12 22:52:26  richard
# more pychecker warnings removed
#
# Revision 1.58  2002/02/27 03:23:16  richard
# Ran it through pychecker, made fixes
#
# Revision 1.57  2002/02/20 05:23:24  richard
# Didn't accomodate new values for new properties
#
# Revision 1.56  2002/02/20 05:05:28  richard
#  . Added simple editing for classes that don't define a templated interface.
#    - access using the admin "class list" interface
#    - limited to admin-only
#    - requires the csv module from object-craft (url given if it's missing)
#
# Revision 1.55  2002/02/15 07:27:12  richard
# Oops, precedences around the way w0rng.
#
# Revision 1.54  2002/02/15 07:08:44  richard
#  . Alternate email addresses are now available for users. See the MIGRATION
#    file for info on how to activate the feature.
#
# Revision 1.53  2002/01/22 07:21:13  richard
# . fixed back_bsddb so it passed the journal tests
#
# ... it didn't seem happy using the back_anydbm _open method, which is odd.
# Yet another occurrance of whichdb not being able to recognise older bsddb
# databases. Yadda yadda. Made the HYPERDBDEBUG stuff more sane in the
# process.
#
# Revision 1.52  2002/01/21 16:33:19  rochecompaan
# You can now use the roundup-admin tool to pack the database
#
# Revision 1.51  2002/01/21 03:01:29  richard
# brief docco on the do_journal argument
#
# Revision 1.50  2002/01/19 13:16:04  rochecompaan
# Journal entries for link and multilink properties can now be switched on
# or off.
#
# Revision 1.49  2002/01/16 07:02:57  richard
#  . lots of date/interval related changes:
#    - more relaxed date format for input
#
# Revision 1.48  2002/01/14 06:32:34  richard
#  . #502951 ] adding new properties to old database
#
# Revision 1.47  2002/01/14 02:20:15  richard
#  . changed all config accesses so they access either the instance or the
#    config attriubute on the db. This means that all config is obtained from
#    instance_config instead of the mish-mash of classes. This will make
#    switching to a ConfigParser setup easier too, I hope.
#
# At a minimum, this makes migration a _little_ easier (a lot easier in the
# 0.5.0 switch, I hope!)
#
# Revision 1.46  2002/01/07 10:42:23  richard
# oops
#
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
