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
#$Id: back_anydbm.py,v 1.96.2.2 2003-02-12 00:03:35 richard Exp $
'''
This module defines a backend that saves the hyperdatabase in a database
chosen by anydbm. It is guaranteed to always be available in python
versions >2.1.1 (the dumbdbm fallback in 2.1.1 and earlier has several
serious bugs, and is not available)
'''

import whichdb, anydbm, os, marshal, re, weakref, string, copy
from roundup import hyperdb, date, password, roundupdb, security
from blobfiles import FileStorage
from sessions import Sessions
from roundup.indexer import Indexer
from roundup.backends import locking
from roundup.hyperdb import String, Password, Date, Interval, Link, \
    Multilink, DatabaseError, Boolean, Number, Node

#
# Now the database
#
class Database(FileStorage, hyperdb.Database, roundupdb.Database):
    '''A database for storing records containing flexible data types.

    Transaction stuff TODO:
        . check the timestamp of the class file and nuke the cache if it's
          modified. Do some sort of conflict checking on the dirty stuff.
        . perhaps detect write collisions (related to above)?

    '''
    def __init__(self, config, journaltag=None):
        '''Open a hyperdatabase given a specifier to some storage.

        The 'storagelocator' is obtained from config.DATABASE.
        The meaning of 'storagelocator' depends on the particular
        implementation of the hyperdatabase.  It could be a file name,
        a directory path, a socket descriptor for a connection to a
        database over the network, etc.

        The 'journaltag' is a token that will be attached to the journal
        entries for any edits done on the database.  If 'journaltag' is
        None, the database is opened in read-only mode: the Class.create(),
        Class.set(), and Class.retire() methods are disabled.
        '''
        self.config, self.journaltag = config, journaltag
        self.dir = config.DATABASE
        self.classes = {}
        self.cache = {}         # cache of nodes loaded or created
        self.dirtynodes = {}    # keep track of the dirty nodes by class
        self.newnodes = {}      # keep track of the new nodes by class
        self.destroyednodes = {}# keep track of the destroyed nodes by class
        self.transactions = []
        self.indexer = Indexer(self.dir)
        self.sessions = Sessions(self.config)
        self.security = security.Security(self)
        # ensure files are group readable and writable
        os.umask(0002)

        # lock it
        lockfilenm = os.path.join(self.dir, 'lock')
        self.lockfile = locking.acquire_lock(lockfilenm)
        self.lockfile.write(str(os.getpid()))
        self.lockfile.flush()

    def post_init(self):
        ''' Called once the schema initialisation has finished.
        '''
        # reindex the db if necessary
        if self.indexer.should_reindex():
            self.reindex()

        # figure the "curuserid"
        if self.journaltag is None:
            self.curuserid = None
        elif self.journaltag == 'admin':
            # admin user may not exist, but always has ID 1
            self.curuserid = '1'
        else:
            self.curuserid = self.user.lookup(self.journaltag)

    def reindex(self):
        for klass in self.classes.values():
            for nodeid in klass.list():
                klass.index(nodeid)
        self.indexer.save_index()

    def __repr__(self):
        return '<back_anydbm instance at %x>'%id(self) 

    #
    # Classes
    #
    def __getattr__(self, classname):
        '''A convenient way of calling self.getclass(classname).'''
        if self.classes.has_key(classname):
            if __debug__:
                print >>hyperdb.DEBUG, '__getattr__', (self, classname)
            return self.classes[classname]
        raise AttributeError, classname

    def addclass(self, cl):
        if __debug__:
            print >>hyperdb.DEBUG, 'addclass', (self, cl)
        cn = cl.classname
        if self.classes.has_key(cn):
            raise ValueError, cn
        self.classes[cn] = cl

    def getclasses(self):
        '''Return a list of the names of all existing classes.'''
        if __debug__:
            print >>hyperdb.DEBUG, 'getclasses', (self,)
        l = self.classes.keys()
        l.sort()
        return l

    def getclass(self, classname):
        '''Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'getclass', (self, classname)
        try:
            return self.classes[classname]
        except KeyError:
            raise KeyError, 'There is no class called "%s"'%classname

    #
    # Class DBs
    #
    def clear(self):
        '''Delete all database contents
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'clear', (self,)
        for cn in self.classes.keys():
            for dummy in 'nodes', 'journals':
                path = os.path.join(self.dir, 'journals.%s'%cn)
                if os.path.exists(path):
                    os.remove(path)
                elif os.path.exists(path+'.db'):    # dbm appends .db
                    os.remove(path+'.db')

    def getclassdb(self, classname, mode='r'):
        ''' grab a connection to the class db that will be used for
            multiple actions
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'getclassdb', (self, classname, mode)
        return self.opendb('nodes.%s'%classname, mode)

    def determine_db_type(self, path):
        ''' determine which DB wrote the class file
        '''
        db_type = ''
        if os.path.exists(path):
            db_type = whichdb.whichdb(path)
            if not db_type:
                raise DatabaseError, "Couldn't identify database type"
        elif os.path.exists(path+'.db'):
            # if the path ends in '.db', it's a dbm database, whether
            # anydbm says it's dbhash or not!
            db_type = 'dbm'
        return db_type

    def opendb(self, name, mode):
        '''Low-level database opener that gets around anydbm/dbm
           eccentricities.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'opendb', (self, name, mode)

        # figure the class db type
        path = os.path.join(os.getcwd(), self.dir, name)
        db_type = self.determine_db_type(path)

        # new database? let anydbm pick the best dbm
        if not db_type:
            if __debug__:
                print >>hyperdb.DEBUG, "opendb anydbm.open(%r, 'c')"%path
            return anydbm.open(path, 'c')

        # open the database with the correct module
        try:
            dbm = __import__(db_type)
        except ImportError:
            raise DatabaseError, \
                "Couldn't open database - the required module '%s'"\
                " is not available"%db_type
        if __debug__:
            print >>hyperdb.DEBUG, "opendb %r.open(%r, %r)"%(db_type, path,
                mode)
        return dbm.open(path, mode)

    #
    # Node IDs
    #
    def newid(self, classname):
        ''' Generate a new id for the given class
        '''
        # open the ids DB - create if if doesn't exist
        db = self.opendb('_ids', 'c')
        if db.has_key(classname):
            newid = db[classname] = str(int(db[classname]) + 1)
        else:
            # the count() bit is transitional - older dbs won't start at 1
            newid = str(self.getclass(classname).count()+1)
            db[classname] = newid
        db.close()
        return newid

    def setid(self, classname, setid):
        ''' Set the id counter: used during import of database
        '''
        # open the ids DB - create if if doesn't exist
        db = self.opendb('_ids', 'c')
        db[classname] = str(setid)
        db.close()

    #
    # Nodes
    #
    def addnode(self, classname, nodeid, node):
        ''' add the specified node to its class's db
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'addnode', (self, classname, nodeid, node)

        # we'll be supplied these props if we're doing an import
        if not node.has_key('creator'):
            # add in the "calculated" properties (dupe so we don't affect
            # calling code's node assumptions)
            node = node.copy()
            node['creator'] = self.curuserid
            node['creation'] = node['activity'] = date.Date()

        self.newnodes.setdefault(classname, {})[nodeid] = 1
        self.cache.setdefault(classname, {})[nodeid] = node
        self.savenode(classname, nodeid, node)

    def setnode(self, classname, nodeid, node):
        ''' change the specified node
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'setnode', (self, classname, nodeid, node)
        self.dirtynodes.setdefault(classname, {})[nodeid] = 1

        # update the activity time (dupe so we don't affect
        # calling code's node assumptions)
        node = node.copy()
        node['activity'] = date.Date()

        # can't set without having already loaded the node
        self.cache[classname][nodeid] = node
        self.savenode(classname, nodeid, node)

    def savenode(self, classname, nodeid, node):
        ''' perform the saving of data specified by the set/addnode
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'savenode', (self, classname, nodeid, node)
        self.transactions.append((self.doSaveNode, (classname, nodeid, node)))

    def getnode(self, classname, nodeid, db=None, cache=1):
        ''' get a node from the database
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'getnode', (self, classname, nodeid, db)
        if cache:
            # try the cache
            cache_dict = self.cache.setdefault(classname, {})
            if cache_dict.has_key(nodeid):
                if __debug__:
                    print >>hyperdb.TRACE, 'get %s %s cached'%(classname,
                        nodeid)
                return cache_dict[nodeid]

        if __debug__:
            print >>hyperdb.TRACE, 'get %s %s'%(classname, nodeid)

        # get from the database and save in the cache
        if db is None:
            db = self.getclassdb(classname)
        if not db.has_key(nodeid):
            raise IndexError, "no such %s %s"%(classname, nodeid)

        # check the uncommitted, destroyed nodes
        if (self.destroyednodes.has_key(classname) and
                self.destroyednodes[classname].has_key(nodeid)):
            raise IndexError, "no such %s %s"%(classname, nodeid)

        # decode
        res = marshal.loads(db[nodeid])

        # reverse the serialisation
        res = self.unserialise(classname, res)

        # store off in the cache dict
        if cache:
            cache_dict[nodeid] = res

        return res

    def destroynode(self, classname, nodeid):
        '''Remove a node from the database. Called exclusively by the
           destroy() method on Class.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'destroynode', (self, classname, nodeid)

        # remove from cache and newnodes if it's there
        if (self.cache.has_key(classname) and
                self.cache[classname].has_key(nodeid)):
            del self.cache[classname][nodeid]
        if (self.newnodes.has_key(classname) and
                self.newnodes[classname].has_key(nodeid)):
            del self.newnodes[classname][nodeid]

        # see if there's any obvious commit actions that we should get rid of
        for entry in self.transactions[:]:
            if entry[1][:2] == (classname, nodeid):
                self.transactions.remove(entry)

        # add to the destroyednodes map
        self.destroyednodes.setdefault(classname, {})[nodeid] = 1

        # add the destroy commit action
        self.transactions.append((self.doDestroyNode, (classname, nodeid)))

    def serialise(self, classname, node):
        '''Copy the node contents, converting non-marshallable data into
           marshallable data.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'serialise', classname, node
        properties = self.getclass(classname).getprops()
        d = {}
        for k, v in node.items():
            # if the property doesn't exist, or is the "retired" flag then
            # it won't be in the properties dict
            if not properties.has_key(k):
                d[k] = v
                continue

            # get the property spec
            prop = properties[k]

            if isinstance(prop, Password) and v is not None:
                d[k] = str(v)
            elif isinstance(prop, Date) and v is not None:
                d[k] = v.serialise()
            elif isinstance(prop, Interval) and v is not None:
                d[k] = v.serialise()
            else:
                d[k] = v
        return d

    def unserialise(self, classname, node):
        '''Decode the marshalled node data
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'unserialise', classname, node
        properties = self.getclass(classname).getprops()
        d = {}
        for k, v in node.items():
            # if the property doesn't exist, or is the "retired" flag then
            # it won't be in the properties dict
            if not properties.has_key(k):
                d[k] = v
                continue

            # get the property spec
            prop = properties[k]

            if isinstance(prop, Date) and v is not None:
                d[k] = date.Date(v)
            elif isinstance(prop, Interval) and v is not None:
                d[k] = date.Interval(v)
            elif isinstance(prop, Password) and v is not None:
                p = password.Password()
                p.unpack(v)
                d[k] = p
            else:
                d[k] = v
        return d

    def hasnode(self, classname, nodeid, db=None):
        ''' determine if the database has a given node
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'hasnode', (self, classname, nodeid, db)

        # try the cache
        cache = self.cache.setdefault(classname, {})
        if cache.has_key(nodeid):
            if __debug__:
                print >>hyperdb.TRACE, 'has %s %s cached'%(classname, nodeid)
            return 1
        if __debug__:
            print >>hyperdb.TRACE, 'has %s %s'%(classname, nodeid)

        # not in the cache - check the database
        if db is None:
            db = self.getclassdb(classname)
        res = db.has_key(nodeid)
        return res

    def countnodes(self, classname, db=None):
        if __debug__:
            print >>hyperdb.DEBUG, 'countnodes', (self, classname, db)

        count = 0

        # include the uncommitted nodes
        if self.newnodes.has_key(classname):
            count += len(self.newnodes[classname])
        if self.destroyednodes.has_key(classname):
            count -= len(self.destroyednodes[classname])

        # and count those in the DB
        if db is None:
            db = self.getclassdb(classname)
        count = count + len(db.keys())
        return count

    def getnodeids(self, classname, db=None):
        if __debug__:
            print >>hyperdb.DEBUG, 'getnodeids', (self, classname, db)

        res = []

        # start off with the new nodes
        if self.newnodes.has_key(classname):
            res += self.newnodes[classname].keys()

        if db is None:
            db = self.getclassdb(classname)
        res = res + db.keys()

        # remove the uncommitted, destroyed nodes
        if self.destroyednodes.has_key(classname):
            for nodeid in self.destroyednodes[classname].keys():
                if db.has_key(nodeid):
                    res.remove(nodeid)

        return res


    #
    # Files - special node properties
    # inherited from FileStorage

    #
    # Journal
    #
    def addjournal(self, classname, nodeid, action, params, creator=None,
            creation=None):
        ''' Journal the Action
        'action' may be:

            'create' or 'set' -- 'params' is a dictionary of property values
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retire' -- 'params' is None
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'addjournal', (self, classname, nodeid,
                action, params, creator, creation)
        self.transactions.append((self.doSaveJournal, (classname, nodeid,
            action, params, creator, creation)))

    def getjournal(self, classname, nodeid):
        ''' get the journal for id

            Raise IndexError if the node doesn't exist (as per history()'s
            API)
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'getjournal', (self, classname, nodeid)
        # attempt to open the journal - in some rare cases, the journal may
        # not exist
        try:
            db = self.opendb('journals.%s'%classname, 'r')
        except anydbm.error, error:
            if str(error) == "need 'c' or 'n' flag to open new db":
                raise IndexError, 'no such %s %s'%(classname, nodeid)
            elif error.args[0] != 2:
                raise
            raise IndexError, 'no such %s %s'%(classname, nodeid)
        try:
            journal = marshal.loads(db[nodeid])
        except KeyError:
            db.close()
            raise IndexError, 'no such %s %s'%(classname, nodeid)
        db.close()
        res = []
        for nodeid, date_stamp, user, action, params in journal:
            res.append((nodeid, date.Date(date_stamp), user, action, params))
        return res

    def pack(self, pack_before):
        ''' Delete all journal entries except "create" before 'pack_before'.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'packjournal', (self, pack_before)

        pack_before = pack_before.serialise()
        for classname in self.getclasses():
            # get the journal db
            db_name = 'journals.%s'%classname
            path = os.path.join(os.getcwd(), self.dir, classname)
            db_type = self.determine_db_type(path)
            db = self.opendb(db_name, 'w')

            for key in db.keys():
                # get the journal for this db entry
                journal = marshal.loads(db[key])
                l = []
                last_set_entry = None
                for entry in journal:
                    # unpack the entry
                    (nodeid, date_stamp, self.journaltag, action, 
                        params) = entry
                    # if the entry is after the pack date, _or_ the initial
                    # create entry, then it stays
                    if date_stamp > pack_before or action == 'create':
                        l.append(entry)
                db[key] = marshal.dumps(l)
            if db_type == 'gdbm':
                db.reorganize()
            db.close()
            

    #
    # Basic transaction support
    #
    def commit(self):
        ''' Commit the current transactions.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'commit', (self,)
        # TODO: lock the DB

        # keep a handle to all the database files opened
        self.databases = {}

        # now, do all the transactions
        reindex = {}
        for method, args in self.transactions:
            reindex[method(*args)] = 1

        # now close all the database files
        for db in self.databases.values():
            db.close()
        del self.databases
        # TODO: unlock the DB

        # reindex the nodes that request it
        for classname, nodeid in filter(None, reindex.keys()):
            print >>hyperdb.DEBUG, 'commit.reindex', (classname, nodeid)
            self.getclass(classname).index(nodeid)

        # save the indexer state
        self.indexer.save_index()

        self.clearCache()

    def clearCache(self):
        # all transactions committed, back to normal
        self.cache = {}
        self.dirtynodes = {}
        self.newnodes = {}
        self.destroyednodes = {}
        self.transactions = []

    def getCachedClassDB(self, classname):
        ''' get the class db, looking in our cache of databases for commit
        '''
        # get the database handle
        db_name = 'nodes.%s'%classname
        if not self.databases.has_key(db_name):
            self.databases[db_name] = self.getclassdb(classname, 'c')
        return self.databases[db_name]

    def doSaveNode(self, classname, nodeid, node):
        if __debug__:
            print >>hyperdb.DEBUG, 'doSaveNode', (self, classname, nodeid,
                node)

        db = self.getCachedClassDB(classname)

        # now save the marshalled data
        db[nodeid] = marshal.dumps(self.serialise(classname, node))

        # return the classname, nodeid so we reindex this content
        return (classname, nodeid)

    def getCachedJournalDB(self, classname):
        ''' get the journal db, looking in our cache of databases for commit
        '''
        # get the database handle
        db_name = 'journals.%s'%classname
        if not self.databases.has_key(db_name):
            self.databases[db_name] = self.opendb(db_name, 'c')
        return self.databases[db_name]

    def doSaveJournal(self, classname, nodeid, action, params, creator,
            creation):
        # serialise the parameters now if necessary
        if isinstance(params, type({})):
            if action in ('set', 'create'):
                params = self.serialise(classname, params)

        # handle supply of the special journalling parameters (usually
        # supplied on importing an existing database)
        if creator:
            journaltag = creator
        else:
            journaltag = self.curuserid
        if creation:
            journaldate = creation.serialise()
        else:
            journaldate = date.Date().serialise()

        # create the journal entry
        entry = (nodeid, journaldate, journaltag, action, params)

        if __debug__:
            print >>hyperdb.DEBUG, 'doSaveJournal', entry

        db = self.getCachedJournalDB(classname)

        # now insert the journal entry
        if db.has_key(nodeid):
            # append to existing
            s = db[nodeid]
            l = marshal.loads(s)
            l.append(entry)
        else:
            l = [entry]

        db[nodeid] = marshal.dumps(l)

    def doDestroyNode(self, classname, nodeid):
        if __debug__:
            print >>hyperdb.DEBUG, 'doDestroyNode', (self, classname, nodeid)

        # delete from the class database
        db = self.getCachedClassDB(classname)
        if db.has_key(nodeid):
            del db[nodeid]

        # delete from the database
        db = self.getCachedJournalDB(classname)
        if db.has_key(nodeid):
            del db[nodeid]

        # return the classname, nodeid so we reindex this content
        return (classname, nodeid)

    def rollback(self):
        ''' Reverse all actions from the current transaction.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'rollback', (self, )
        for method, args in self.transactions:
            # delete temporary files
            if method == self.doStoreFile:
                self.rollbackStoreFile(*args)
        self.cache = {}
        self.dirtynodes = {}
        self.newnodes = {}
        self.destroyednodes = {}
        self.transactions = []

    def close(self):
        ''' Nothing to do
        '''
        if self.lockfile is not None:
            locking.release_lock(self.lockfile)
        if self.lockfile is not None:
            self.lockfile.close()
            self.lockfile = None

_marker = []
class Class(hyperdb.Class):
    '''The handle to a particular class of nodes in a hyperdatabase.'''

    def __init__(self, db, classname, **properties):
        '''Create a new class with a given name and property specification.

        'classname' must not collide with the name of an existing class,
        or a ValueError is raised.  The keyword arguments in 'properties'
        must map names to property objects, or a TypeError is raised.
        '''
        if (properties.has_key('creation') or properties.has_key('activity')
                or properties.has_key('creator')):
            raise ValueError, '"creation", "activity" and "creator" are '\
                'reserved'

        self.classname = classname
        self.properties = properties
        self.db = weakref.proxy(db)       # use a weak ref to avoid circularity
        self.key = ''

        # should we journal changes (default yes)
        self.do_journal = 1

        # do the db-related init stuff
        db.addclass(self)

        self.auditors = {'create': [], 'set': [], 'retire': []}
        self.reactors = {'create': [], 'set': [], 'retire': []}

    def enableJournalling(self):
        '''Turn journalling on for this class
        '''
        self.do_journal = 1

    def disableJournalling(self):
        '''Turn journalling off for this class
        '''
        self.do_journal = 0

    # Editing nodes:

    def create(self, **propvalues):
        '''Create a new node of this class and return its id.

        The keyword arguments in 'propvalues' map property names to values.

        The values of arguments must be acceptable for the types of their
        corresponding properties or a TypeError is raised.
        
        If this class has a key property, it must be present and its value
        must not collide with other key strings or a ValueError is raised.
        
        Any other properties on this class that are missing from the
        'propvalues' dictionary are set to None.
        
        If an id in a link or multilink property does not refer to a valid
        node, an IndexError is raised.

        These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        '''
        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'

        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'

        if propvalues.has_key('creation') or propvalues.has_key('activity'):
            raise KeyError, '"creation" and "activity" are reserved'

        self.fireAuditors('create', None, propvalues)

        # new node's id
        newid = self.db.newid(self.classname)

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

            if value is not None and isinstance(prop, Link):
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
                elif not self.db.getclass(link_class).hasnode(value):
                    raise IndexError, '%s has no node %s'%(link_class, value)

                # save off the value
                propvalues[key] = value

                # register the link with the newly linked node
                if self.do_journal and self.properties[key].do_journal:
                    self.db.addjournal(link_class, value, 'link',
                        (self.classname, newid, key))

            elif isinstance(prop, Multilink):
                if type(value) != type([]):
                    raise TypeError, 'new property "%s" not a list of ids'%key

                # clean up and validate the list of links
                link_class = self.properties[key].classname
                l = []
                for entry in value:
                    if type(entry) != type(''):
                        raise ValueError, '"%s" multilink value (%r) '\
                            'must contain Strings'%(key, value)
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
                for nodeid in value:
                    if not self.db.getclass(link_class).hasnode(nodeid):
                        raise IndexError, '%s has no node %s'%(link_class,
                            nodeid)
                    # register the link with the newly linked node
                    if self.do_journal and self.properties[key].do_journal:
                        self.db.addjournal(link_class, nodeid, 'link',
                            (self.classname, newid, key))

            elif isinstance(prop, String):
                if type(value) != type(''):
                    raise TypeError, 'new property "%s" not a string'%key

            elif isinstance(prop, Password):
                if not isinstance(value, password.Password):
                    raise TypeError, 'new property "%s" not a Password'%key

            elif isinstance(prop, Date):
                if value is not None and not isinstance(value, date.Date):
                    raise TypeError, 'new property "%s" not a Date'%key

            elif isinstance(prop, Interval):
                if value is not None and not isinstance(value, date.Interval):
                    raise TypeError, 'new property "%s" not an Interval'%key

            elif value is not None and isinstance(prop, Number):
                try:
                    float(value)
                except ValueError:
                    raise TypeError, 'new property "%s" not numeric'%key

            elif value is not None and isinstance(prop, Boolean):
                try:
                    int(value)
                except ValueError:
                    raise TypeError, 'new property "%s" not boolean'%key

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

        # done
        self.db.addnode(self.classname, newid, propvalues)
        if self.do_journal:
            self.db.addjournal(self.classname, newid, 'create', {})

        self.fireReactors('create', newid, None)

        return newid

    def export_list(self, propnames, nodeid):
        ''' Export a node - generate a list of CSV-able data in the order
            specified by propnames for the given node.
        '''
        properties = self.getprops()
        l = []
        for prop in propnames:
            proptype = properties[prop]
            value = self.get(nodeid, prop)
            # "marshal" data where needed
            if value is None:
                pass
            elif isinstance(proptype, hyperdb.Date):
                value = value.get_tuple()
            elif isinstance(proptype, hyperdb.Interval):
                value = value.get_tuple()
            elif isinstance(proptype, hyperdb.Password):
                value = str(value)
            l.append(repr(value))
        return l

    def import_list(self, propnames, proplist):
        ''' Import a node - all information including "id" is present and
            should not be sanity checked. Triggers are not triggered. The
            journal should be initialised using the "creator" and "created"
            information.

            Return the nodeid of the node imported.
        '''
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'
        properties = self.getprops()

        # make the new node's property map
        d = {}
        for i in range(len(propnames)):
            # Use eval to reverse the repr() used to output the CSV
            value = eval(proplist[i])

            # Figure the property for this column
            propname = propnames[i]
            prop = properties[propname]

            # "unmarshal" where necessary
            if propname == 'id':
                newid = value
                continue
            elif value is None:
                # don't set Nones
                continue
            elif isinstance(prop, hyperdb.Date):
                value = date.Date(value)
            elif isinstance(prop, hyperdb.Interval):
                value = date.Interval(value)
            elif isinstance(prop, hyperdb.Password):
                pwd = password.Password()
                pwd.unpack(value)
                value = pwd
            d[propname] = value

        # add the node and journal
        self.db.addnode(self.classname, newid, d)

        # extract the journalling stuff and nuke it
        if d.has_key('creator'):
            creator = d['creator']
            del d['creator']
        else:
            creator = None
        if d.has_key('creation'):
            creation = d['creation']
            del d['creation']
        else:
            creation = None
        if d.has_key('activity'):
            del d['activity']
        self.db.addjournal(self.classname, newid, 'create', {}, creator,
            creation)
        return newid

    def get(self, nodeid, propname, default=_marker, cache=1):
        '''Get the value of a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.  'propname' must be the name of a property
        of this class or a KeyError is raised.

        'cache' indicates whether the transaction cache should be queried
        for the node. If the node has been modified and you need to
        determine what its values prior to modification are, you need to
        set cache=0.

        Attempts to get the "creation" or "activity" properties should
        do the right thing.
        '''
        if propname == 'id':
            return nodeid

        # get the node's dict
        d = self.db.getnode(self.classname, nodeid, cache=cache)

        # check for one of the special props
        if propname == 'creation':
            if d.has_key('creation'):
                return d['creation']
            if not self.do_journal:
                raise ValueError, 'Journalling is disabled for this class'
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                return self.db.getjournal(self.classname, nodeid)[0][1]
            else:
                # on the strange chance that there's no journal
                return date.Date()
        if propname == 'activity':
            if d.has_key('activity'):
                return d['activity']
            if not self.do_journal:
                raise ValueError, 'Journalling is disabled for this class'
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                return self.db.getjournal(self.classname, nodeid)[-1][1]
            else:
                # on the strange chance that there's no journal
                return date.Date()
        if propname == 'creator':
            if d.has_key('creator'):
                return d['creator']
            if not self.do_journal:
                raise ValueError, 'Journalling is disabled for this class'
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                num_re = re.compile('^\d+$')
                value = self.db.getjournal(self.classname, nodeid)[0][2]
                if num_re.match(value):
                    return value
                else:
                    # old-style "username" journal tag
                    try:
                        return self.db.user.lookup(value)
                    except KeyError:
                        # user's been retired, return admin
                        return '1'
            else:
                return self.db.curuserid

        # get the property (raises KeyErorr if invalid)
        prop = self.properties[propname]

        if not d.has_key(propname):
            if default is _marker:
                if isinstance(prop, Multilink):
                    return []
                else:
                    return None
            else:
                return default

        # return a dupe of the list so code doesn't get confused
        if isinstance(prop, Multilink):
            return d[propname][:]

        return d[propname]

    # not in spec
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
        '''Modify a property on an existing node of this class.
        
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

        These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        '''
        if not propvalues:
            return propvalues

        if propvalues.has_key('creation') or propvalues.has_key('activity'):
            raise KeyError, '"creation" and "activity" are reserved'

        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'

        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'

        self.fireAuditors('set', nodeid, propvalues)
        # Take a copy of the node dict so that the subsequent set
        # operation doesn't modify the oldvalues structure.
        try:
            # try not using the cache initially
            oldvalues = copy.deepcopy(self.db.getnode(self.classname, nodeid,
                cache=0))
        except IndexError:
            # this will be needed if somone does a create() and set()
            # with no intervening commit()
            oldvalues = copy.deepcopy(self.db.getnode(self.classname, nodeid))

        node = self.db.getnode(self.classname, nodeid)
        if node.has_key(self.db.RETIRED_FLAG):
            raise IndexError
        num_re = re.compile('^\d+$')

        # if the journal value is to be different, store it in here
        journalvalues = {}

        for propname, value in propvalues.items():
            # check to make sure we're not duplicating an existing key
            if propname == self.key and node[propname] != value:
                try:
                    self.lookup(value)
                except KeyError:
                    pass
                else:
                    raise ValueError, 'node with key "%s" exists'%value

            # this will raise the KeyError if the property isn't valid
            # ... we don't use getprops() here because we only care about
            # the writeable properties.
            try:
                prop = self.properties[propname]
            except KeyError:
                raise KeyError, '"%s" has no property named "%s"'%(
                    self.classname, propname)

            # if the value's the same as the existing value, no sense in
            # doing anything
            current = node.get(propname, None)
            if value == current:
                del propvalues[propname]
                continue
            journalvalues[propname] = current

            # do stuff based on the prop type
            if isinstance(prop, Link):
                link_class = prop.classname
                # if it isn't a number, it's a key
                if value is not None and not isinstance(value, type('')):
                    raise ValueError, 'property "%s" link value be a string'%(
                        propname)
                if isinstance(value, type('')) and not num_re.match(value):
                    try:
                        value = self.db.classes[link_class].lookup(value)
                    except (TypeError, KeyError):
                        raise IndexError, 'new property "%s": %s not a %s'%(
                            propname, value, prop.classname)

                if (value is not None and
                        not self.db.getclass(link_class).hasnode(value)):
                    raise IndexError, '%s has no node %s'%(link_class, value)

                if self.do_journal and prop.do_journal:
                    # register the unlink with the old linked node
                    if node.has_key(propname) and node[propname] is not None:
                        self.db.addjournal(link_class, node[propname], 'unlink',
                            (self.classname, nodeid, propname))

                    # register the link with the newly linked node
                    if value is not None:
                        self.db.addjournal(link_class, value, 'link',
                            (self.classname, nodeid, propname))

            elif isinstance(prop, Multilink):
                if type(value) != type([]):
                    raise TypeError, 'new property "%s" not a list of'\
                        ' ids'%propname
                link_class = self.properties[propname].classname
                l = []
                for entry in value:
                    # if it isn't a number, it's a key
                    if type(entry) != type(''):
                        raise ValueError, 'new property "%s" link value ' \
                            'must be a string'%propname
                    if not num_re.match(entry):
                        try:
                            entry = self.db.classes[link_class].lookup(entry)
                        except (TypeError, KeyError):
                            raise IndexError, 'new property "%s": %s not a %s'%(
                                propname, entry,
                                self.properties[propname].classname)
                    l.append(entry)
                value = l
                propvalues[propname] = value

                # figure the journal entry for this property
                add = []
                remove = []

                # handle removals
                if node.has_key(propname):
                    l = node[propname]
                else:
                    l = []
                for id in l[:]:
                    if id in value:
                        continue
                    # register the unlink with the old linked node
                    if self.do_journal and self.properties[propname].do_journal:
                        self.db.addjournal(link_class, id, 'unlink',
                            (self.classname, nodeid, propname))
                    l.remove(id)
                    remove.append(id)

                # handle additions
                for id in value:
                    if not self.db.getclass(link_class).hasnode(id):
                        raise IndexError, '%s has no node %s'%(link_class, id)
                    if id in l:
                        continue
                    # register the link with the newly linked node
                    if self.do_journal and self.properties[propname].do_journal:
                        self.db.addjournal(link_class, id, 'link',
                            (self.classname, nodeid, propname))
                    l.append(id)
                    add.append(id)

                # figure the journal entry
                l = []
                if add:
                    l.append(('+', add))
                if remove:
                    l.append(('-', remove))
                if l:
                    journalvalues[propname] = tuple(l)

            elif isinstance(prop, String):
                if value is not None and type(value) != type(''):
                    raise TypeError, 'new property "%s" not a string'%propname

            elif isinstance(prop, Password):
                if not isinstance(value, password.Password):
                    raise TypeError, 'new property "%s" not a Password'%propname
                propvalues[propname] = value

            elif value is not None and isinstance(prop, Date):
                if not isinstance(value, date.Date):
                    raise TypeError, 'new property "%s" not a Date'% propname
                propvalues[propname] = value

            elif value is not None and isinstance(prop, Interval):
                if not isinstance(value, date.Interval):
                    raise TypeError, 'new property "%s" not an '\
                        'Interval'%propname
                propvalues[propname] = value

            elif value is not None and isinstance(prop, Number):
                try:
                    float(value)
                except ValueError:
                    raise TypeError, 'new property "%s" not numeric'%propname

            elif value is not None and isinstance(prop, Boolean):
                try:
                    int(value)
                except ValueError:
                    raise TypeError, 'new property "%s" not boolean'%propname

            node[propname] = value

        # nothing to do?
        if not propvalues:
            return propvalues

        # do the set, and journal it
        self.db.setnode(self.classname, nodeid, node)

        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, 'set', journalvalues)

        self.fireReactors('set', nodeid, oldvalues)

        return propvalues        

    def retire(self, nodeid):
        '''Retire a node.
        
        The properties on the node remain available from the get() method,
        and the node's id is never reused.
        
        Retired nodes are not returned by the find(), list(), or lookup()
        methods, and other nodes may reuse the values of their key properties.

        These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        '''
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'

        self.fireAuditors('retire', nodeid, None)

        node = self.db.getnode(self.classname, nodeid)
        node[self.db.RETIRED_FLAG] = 1
        self.db.setnode(self.classname, nodeid, node)
        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, 'retired', None)

        self.fireReactors('retire', nodeid, None)

    def is_retired(self, nodeid):
        '''Return true if the node is retired.
        '''
        node = self.db.getnode(cn, nodeid, cldb)
        if node.has_key(self.db.RETIRED_FLAG):
            return 1
        return 0

    def destroy(self, nodeid):
        '''Destroy a node.

        WARNING: this method should never be used except in extremely rare
                 situations where there could never be links to the node being
                 deleted
        WARNING: use retire() instead
        WARNING: the properties of this node will not be available ever again
        WARNING: really, use retire() instead

        Well, I think that's enough warnings. This method exists mostly to
        support the session storage of the cgi interface.
        '''
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'
        self.db.destroynode(self.classname, nodeid)

    def history(self, nodeid):
        '''Retrieve the journal of edits on a particular node.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.

        The returned list contains tuples of the form

            (nodeid, date, tag, action, params)

        'date' is a Timestamp object specifying the time of the change and
        'tag' is the journaltag specified when the database was opened.
        '''
        if not self.do_journal:
            raise ValueError, 'Journalling is disabled for this class'
        return self.db.getjournal(self.classname, nodeid)

    # Locating nodes:
    def hasnode(self, nodeid):
        '''Determine if the given nodeid actually exists
        '''
        return self.db.hasnode(self.classname, nodeid)

    def setkey(self, propname):
        '''Select a String property of this class to be the key property.

        'propname' must be the name of a String property of this class or
        None, or a TypeError is raised.  The values of the key property on
        all existing nodes must be unique or a ValueError is raised. If the
        property doesn't exist, KeyError is raised.
        '''
        prop = self.getprops()[propname]
        if not isinstance(prop, String):
            raise TypeError, 'key properties must be String'
        self.key = propname

    def getkey(self):
        '''Return the name of the key property for this class or None.'''
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
        '''Locate a particular node by its key property and return its id.

        If this class has no key property, a TypeError is raised.  If the
        'keyvalue' matches one of the values for the key property among
        the nodes in this class, the matching node's id is returned;
        otherwise a KeyError is raised.
        '''
        if not self.key:
            raise TypeError, 'No key property set for class %s'%self.classname
        cldb = self.db.getclassdb(self.classname)
        try:
            for nodeid in self.db.getnodeids(self.classname, cldb):
                node = self.db.getnode(self.classname, nodeid, cldb)
                if node.has_key(self.db.RETIRED_FLAG):
                    continue
                if node[self.key] == keyvalue:
                    return nodeid
        finally:
            cldb.close()
        raise KeyError, 'No key (%s) value "%s" for "%s"'%(self.key,
            keyvalue, self.classname)

    # change from spec - allows multiple props to match
    def find(self, **propspec):
        '''Get the ids of nodes in this class which link to the given nodes.

        'propspec' consists of keyword args propname=nodeid or
                   propname={nodeid:1, }
        'propname' must be the name of a property in this class, or a
                   KeyError is raised.  That property must be a Link or
                   Multilink property, or a TypeError is raised.

        Any node in this class whose 'propname' property links to any of the
        nodeids will be returned. Used by the full text indexing, which knows
        that "foo" occurs in msg1, msg3 and file7, so we have hits on these
        issues:

            db.issue.find(messages={'1':1,'3':1}, files={'7':1})
        '''
        propspec = propspec.items()
        for propname, nodeids in propspec:
            # check the prop is OK
            prop = self.properties[propname]
            if not isinstance(prop, Link) and not isinstance(prop, Multilink):
                raise TypeError, "'%s' not a Link/Multilink property"%propname

        # ok, now do the find
        cldb = self.db.getclassdb(self.classname)
        l = []
        try:
            for id in self.db.getnodeids(self.classname, db=cldb):
                node = self.db.getnode(self.classname, id, db=cldb)
                if node.has_key(self.db.RETIRED_FLAG):
                    continue
                for propname, nodeids in propspec:
                    # can't test if the node doesn't have this property
                    if not node.has_key(propname):
                        continue
                    if type(nodeids) is type(''):
                        nodeids = {nodeids:1}
                    prop = self.properties[propname]
                    value = node[propname]
                    if isinstance(prop, Link) and nodeids.has_key(value):
                        l.append(id)
                        break
                    elif isinstance(prop, Multilink):
                        hit = 0
                        for v in value:
                            if nodeids.has_key(v):
                                l.append(id)
                                hit = 1
                                break
                        if hit:
                            break
        finally:
            cldb.close()
        return l

    def stringFind(self, **requirements):
        '''Locate a particular node by matching a set of its String
        properties in a caseless search.

        If the property is not a String property, a TypeError is raised.
        
        The return is a list of the id of all nodes that match.
        '''
        for propname in requirements.keys():
            prop = self.properties[propname]
            if isinstance(not prop, String):
                raise TypeError, "'%s' not a String property"%propname
            requirements[propname] = requirements[propname].lower()
        l = []
        cldb = self.db.getclassdb(self.classname)
        try:
            for nodeid in self.db.getnodeids(self.classname, cldb):
                node = self.db.getnode(self.classname, nodeid, cldb)
                if node.has_key(self.db.RETIRED_FLAG):
                    continue
                for key, value in requirements.items():
                    if not node.has_key(key):
                        break
                    if node[key] is None or node[key].lower() != value:
                        break
                else:
                    l.append(nodeid)
        finally:
            cldb.close()
        return l

    def list(self):
        ''' Return a list of the ids of the active nodes in this class.
        '''
        l = []
        cn = self.classname
        cldb = self.db.getclassdb(cn)
        try:
            for nodeid in self.db.getnodeids(cn, cldb):
                node = self.db.getnode(cn, nodeid, cldb)
                if node.has_key(self.db.RETIRED_FLAG):
                    continue
                l.append(nodeid)
        finally:
            cldb.close()
        l.sort()
        return l

    def filter(self, search_matches, filterspec, sort=(None,None),
            group=(None,None), num_re = re.compile('^\d+$')):
        ''' Return a list of the ids of the active nodes in this class that
            match the 'filter' spec, sorted by the group spec and then the
            sort spec.

            "filterspec" is {propname: value(s)}
            "sort" and "group" are (dir, prop) where dir is '+', '-' or None
                               and prop is a prop name or None
            "search_matches" is {nodeid: marker}

            The filter must match all properties specificed - but if the
            property value to match is a list, any one of the values in the
            list may match for that property to match.
        '''
        cn = self.classname

        # optimise filterspec
        l = []
        props = self.getprops()
        LINK = 0
        MULTILINK = 1
        STRING = 2
        OTHER = 6
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

                l.append((LINK, k, u))
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
                l.append((MULTILINK, k, u))
            elif isinstance(propclass, String) and k != 'id':
                # simple glob searching
                v = re.sub(r'([\|\{\}\\\.\+\[\]\(\)])', r'\\\1', v)
                v = v.replace('?', '.')
                v = v.replace('*', '.*?')
                l.append((STRING, k, re.compile(v, re.I)))
            elif isinstance(propclass, Boolean):
                if type(v) is type(''):
                    bv = v.lower() in ('yes', 'true', 'on', '1')
                else:
                    bv = v
                l.append((OTHER, k, bv))
            elif isinstance(propclass, Date):
                l.append((OTHER, k, date.Date(v)))
            elif isinstance(propclass, Interval):
                l.append((OTHER, k, date.Interval(v)))
            elif isinstance(propclass, Number):
                l.append((OTHER, k, int(v)))
            else:
                l.append((OTHER, k, v))
        filterspec = l

        # now, find all the nodes that are active and pass filtering
        l = []
        cldb = self.db.getclassdb(cn)
        try:
            # TODO: only full-scan once (use items())
            for nodeid in self.db.getnodeids(cn, cldb):
                node = self.db.getnode(cn, nodeid, cldb)
                if node.has_key(self.db.RETIRED_FLAG):
                    continue
                # apply filter
                for t, k, v in filterspec:
                    # handle the id prop
                    if k == 'id' and v == nodeid:
                        continue

                    # make sure the node has the property
                    if not node.has_key(k):
                        # this node doesn't have this property, so reject it
                        break

                    # now apply the property filter
                    if t == LINK:
                        # link - if this node's property doesn't appear in the
                        # filterspec's nodeid list, skip it
                        if node[k] not in v:
                            break
                    elif t == MULTILINK:
                        # multilink - if any of the nodeids required by the
                        # filterspec aren't in this node's property, then skip
                        # it
                        have = node[k]
                        for want in v:
                            if want not in have:
                                break
                        else:
                            continue
                        break
                    elif t == STRING:
                        # RE search
                        if node[k] is None or not v.search(node[k]):
                            break
                    elif t == OTHER:
                        # straight value comparison for the other types
                        if node[k] != v:
                            break
                else:
                    l.append((nodeid, node))
        finally:
            cldb.close()
        l.sort()

        # filter based on full text search
        if search_matches is not None:
            k = []
            for v in l:
                if search_matches.has_key(v[0]):
                    k.append(v)
            l = k

        # now, sort the result
        def sortfun(a, b, sort=sort, group=group, properties=self.getprops(),
                db = self.db, cl=self):
            a_id, an = a
            b_id, bn = b
            # sort by group and then sort
            for dir, prop in group, sort:
                if dir is None or prop is None: continue

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
                        av = av.lower()
                    if bv and bv[0] in string.uppercase:
                        bv = bv.lower()
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
                elif isinstance(propclass, Number) or isinstance(propclass, Boolean):
                    if dir == '+':
                        r = cmp(av, bv)
                    elif dir == '-':
                        r = cmp(bv, av)
                    
            # end for dir, prop in sort, group:
            # if all else fails, compare the ids
            return cmp(a[0], b[0])

        l.sort(sortfun)
        return [i[0] for i in l]

    def count(self):
        '''Get the number of nodes in this class.

        If the returned integer is 'numnodes', the ids of all the nodes
        in this class run from 1 to numnodes, and numnodes+1 will be the
        id of the next node to be created in this class.
        '''
        return self.db.countnodes(self.classname)

    # Manipulating properties:

    def getprops(self, protected=1):
        '''Return a dictionary mapping property names to property objects.
           If the "protected" flag is true, we include protected properties -
           those which may not be modified.

           In addition to the actual properties on the node, these
           methods provide the "creation" and "activity" properties. If the
           "protected" flag is true, we include protected properties - those
           which may not be modified.
        '''
        d = self.properties.copy()
        if protected:
            d['id'] = String()
            d['creation'] = hyperdb.Date()
            d['activity'] = hyperdb.Date()
            d['creator'] = hyperdb.Link('user')
        return d

    def addprop(self, **properties):
        '''Add properties to this class.

        The keyword arguments in 'properties' must map names to property
        objects, or a TypeError is raised.  None of the keys in 'properties'
        may collide with the names of existing properties, or a ValueError
        is raised before any properties have been added.
        '''
        for key in properties.keys():
            if self.properties.has_key(key):
                raise ValueError, key
        self.properties.update(properties)

    def index(self, nodeid):
        '''Add (or refresh) the node to search indexes
        '''
        # find all the String properties that have indexme
        for prop, propclass in self.getprops().items():
            if isinstance(propclass, String) and propclass.indexme:
                try:
                    value = str(self.get(nodeid, prop))
                except IndexError:
                    # node no longer exists - entry should be removed
                    self.db.indexer.purge_entry((self.classname, nodeid, prop))
                else:
                    # and index them under (classname, nodeid, property)
                    self.db.indexer.add_text((self.classname, nodeid, prop),
                        value)

    #
    # Detector interface
    #
    def audit(self, event, detector):
        '''Register a detector
        '''
        l = self.auditors[event]
        if detector not in l:
            self.auditors[event].append(detector)

    def fireAuditors(self, action, nodeid, newvalues):
        '''Fire all registered auditors.
        '''
        for audit in self.auditors[action]:
            audit(self.db, self, nodeid, newvalues)

    def react(self, event, detector):
        '''Register a detector
        '''
        l = self.reactors[event]
        if detector not in l:
            self.reactors[event].append(detector)

    def fireReactors(self, action, nodeid, oldvalues):
        '''Fire all registered reactors.
        '''
        for react in self.reactors[action]:
            react(self.db, self, nodeid, oldvalues)

class FileClass(Class):
    '''This class defines a large chunk of data. To support this, it has a
       mandatory String property "content" which is typically saved off
       externally to the hyperdb.

       The default MIME type of this data is defined by the
       "default_mime_type" class attribute, which may be overridden by each
       node if the class defines a "type" String property.
    '''
    default_mime_type = 'text/plain'

    def create(self, **propvalues):
        ''' snaffle the file propvalue and store in a file
        '''
        content = propvalues['content']
        del propvalues['content']
        newid = Class.create(self, **propvalues)
        self.db.storefile(self.classname, newid, None, content)
        return newid

    def import_list(self, propnames, proplist):
        ''' Trap the "content" property...
        '''
        # dupe this list so we don't affect others
        propnames = propnames[:]

        # extract the "content" property from the proplist
        i = propnames.index('content')
        content = eval(proplist[i])
        del propnames[i]
        del proplist[i]

        # do the normal import
        newid = Class.import_list(self, propnames, proplist)

        # save off the "content" file
        self.db.storefile(self.classname, newid, None, content)
        return newid

    def get(self, nodeid, propname, default=_marker, cache=1):
        ''' trap the content propname and get it from the file
        '''
        poss_msg = 'Possibly an access right configuration problem.'
        if propname == 'content':
            try:
                return self.db.getfile(self.classname, nodeid, None)
            except IOError, (strerror):
                # XXX by catching this we donot see an error in the log.
                return 'ERROR reading file: %s%s\n%s\n%s'%(
                        self.classname, nodeid, poss_msg, strerror)
        if default is not _marker:
            return Class.get(self, nodeid, propname, default, cache=cache)
        else:
            return Class.get(self, nodeid, propname, cache=cache)

    def getprops(self, protected=1):
        ''' In addition to the actual properties on the node, these methods
            provide the "content" property. If the "protected" flag is true,
            we include protected properties - those which may not be
            modified.
        '''
        d = Class.getprops(self, protected=protected).copy()
        d['content'] = hyperdb.String()
        return d

    def index(self, nodeid):
        ''' Index the node in the search index.

            We want to index the content in addition to the normal String
            property indexing.
        '''
        # perform normal indexing
        Class.index(self, nodeid)

        # get the content to index
        content = self.get(nodeid, 'content')

        # figure the mime type
        if self.properties.has_key('type'):
            mime_type = self.get(nodeid, 'type')
        else:
            mime_type = self.default_mime_type

        # and index!
        self.db.indexer.add_text((self.classname, nodeid, 'content'), content,
            mime_type)

# deviation from spec - was called ItemClass
class IssueClass(Class, roundupdb.IssueClass):
    # Overridden methods:
    def __init__(self, db, classname, **properties):
        '''The newly-created class automatically includes the "messages",
        "files", "nosy", and "superseder" properties.  If the 'properties'
        dictionary attempts to specify any of these properties or a
        "creation" or "activity" property, a ValueError is raised.
        '''
        if not properties.has_key('title'):
            properties['title'] = hyperdb.String(indexme='yes')
        if not properties.has_key('messages'):
            properties['messages'] = hyperdb.Multilink("msg")
        if not properties.has_key('files'):
            properties['files'] = hyperdb.Multilink("file")
        if not properties.has_key('nosy'):
            # note: journalling is turned off as it really just wastes
            # space. this behaviour may be overridden in an instance
            properties['nosy'] = hyperdb.Multilink("user", do_journal="no")
        if not properties.has_key('superseder'):
            properties['superseder'] = hyperdb.Multilink(classname)
        Class.__init__(self, db, classname, **properties)

#
