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
#$Id: back_anydbm.py,v 1.202 2006-08-29 04:20:50 richard Exp $
'''This module defines a backend that saves the hyperdatabase in a
database chosen by anydbm. It is guaranteed to always be available in python
versions >2.1.1 (the dumbdbm fallback in 2.1.1 and earlier has several
serious bugs, and is not available)
'''
__docformat__ = 'restructuredtext'

try:
    import anydbm, sys
    # dumbdbm only works in python 2.1.2+
    if sys.version_info < (2,1,2):
        import dumbdbm
        assert anydbm._defaultmod != dumbdbm
        del dumbdbm
except AssertionError:
    print "WARNING: you should upgrade to python 2.1.3"

import whichdb, os, marshal, re, weakref, string, copy, time, shutil, logging

from roundup import hyperdb, date, password, roundupdb, security, support
from roundup.support import reversed
from roundup.backends import locking
from roundup.i18n import _

from blobfiles import FileStorage
from sessions_dbm import Sessions, OneTimeKeys

try:
    from indexer_xapian import Indexer
except ImportError:
    from indexer_dbm import Indexer

def db_exists(config):
    # check for the user db
    for db in 'nodes.user nodes.user.db'.split():
        if os.path.exists(os.path.join(config.DATABASE, db)):
            return 1
    return 0

def db_nuke(config):
    shutil.rmtree(config.DATABASE)

#
# Now the database
#
class Database(FileStorage, hyperdb.Database, roundupdb.Database):
    '''A database for storing records containing flexible data types.

    Transaction stuff TODO:

    - check the timestamp of the class file and nuke the cache if it's
      modified. Do some sort of conflict checking on the dirty stuff.
    - perhaps detect write collisions (related to above)?
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
        Class.set(), Class.retire(), and Class.restore() methods are
        disabled.
        '''
        self.config, self.journaltag = config, journaltag
        self.dir = config.DATABASE
        self.classes = {}
        self.cache = {}         # cache of nodes loaded or created
        self.stats = {'cache_hits': 0, 'cache_misses': 0, 'get_items': 0,
            'filtering': 0}
        self.dirtynodes = {}    # keep track of the dirty nodes by class
        self.newnodes = {}      # keep track of the new nodes by class
        self.destroyednodes = {}# keep track of the destroyed nodes by class
        self.transactions = []
        self.indexer = Indexer(self)
        self.security = security.Security(self)
        os.umask(config.UMASK)

        # lock it
        lockfilenm = os.path.join(self.dir, 'lock')
        self.lockfile = locking.acquire_lock(lockfilenm)
        self.lockfile.write(str(os.getpid()))
        self.lockfile.flush()

    def post_init(self):
        '''Called once the schema initialisation has finished.
        '''
        # reindex the db if necessary
        if self.indexer.should_reindex():
            self.reindex()

    def refresh_database(self):
        """Rebuild the database
        """
        self.reindex()

    def getSessionManager(self):
        return Sessions(self)

    def getOTKManager(self):
        return OneTimeKeys(self)

    def reindex(self, classname=None, show_progress=False):
        if classname:
            classes = [self.getclass(classname)]
        else:
            classes = self.classes.values()
        for klass in classes:
            if show_progress:
                for nodeid in support.Progress('Reindex %s'%klass.classname,
                        klass.list()):
                    klass.index(nodeid)
            else:
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
            return self.classes[classname]
        raise AttributeError, classname

    def addclass(self, cl):
        cn = cl.classname
        if self.classes.has_key(cn):
            raise ValueError, cn
        self.classes[cn] = cl

        # add default Edit and View permissions
        self.security.addPermission(name="Create", klass=cn,
            description="User is allowed to create "+cn)
        self.security.addPermission(name="Edit", klass=cn,
            description="User is allowed to edit "+cn)
        self.security.addPermission(name="View", klass=cn,
            description="User is allowed to access "+cn)

    def getclasses(self):
        '''Return a list of the names of all existing classes.'''
        l = self.classes.keys()
        l.sort()
        return l

    def getclass(self, classname):
        '''Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        '''
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
        logging.getLogger('hyperdb').info('clear')
        for cn in self.classes.keys():
            for dummy in 'nodes', 'journals':
                path = os.path.join(self.dir, 'journals.%s'%cn)
                if os.path.exists(path):
                    os.remove(path)
                elif os.path.exists(path+'.db'):    # dbm appends .db
                    os.remove(path+'.db')
        # reset id sequences
        path = os.path.join(os.getcwd(), self.dir, '_ids')
        if os.path.exists(path):
            os.remove(path)
        elif os.path.exists(path+'.db'):    # dbm appends .db
            os.remove(path+'.db')

    def getclassdb(self, classname, mode='r'):
        ''' grab a connection to the class db that will be used for
            multiple actions
        '''
        return self.opendb('nodes.%s'%classname, mode)

    def determine_db_type(self, path):
        ''' determine which DB wrote the class file
        '''
        db_type = ''
        if os.path.exists(path):
            db_type = whichdb.whichdb(path)
            if not db_type:
                raise hyperdb.DatabaseError, "Couldn't identify database type"
        elif os.path.exists(path+'.db'):
            # if the path ends in '.db', it's a dbm database, whether
            # anydbm says it's dbhash or not!
            db_type = 'dbm'
        return db_type

    def opendb(self, name, mode):
        '''Low-level database opener that gets around anydbm/dbm
           eccentricities.
        '''
        # figure the class db type
        path = os.path.join(os.getcwd(), self.dir, name)
        db_type = self.determine_db_type(path)

        # new database? let anydbm pick the best dbm
        if not db_type:
            if __debug__:
                logging.getLogger('hyperdb').debug("opendb anydbm.open(%r, 'c')"%path)
            return anydbm.open(path, 'c')

        # open the database with the correct module
        try:
            dbm = __import__(db_type)
        except ImportError:
            raise hyperdb.DatabaseError, \
                "Couldn't open database - the required module '%s'"\
                " is not available"%db_type
        if __debug__:
            logging.getLogger('hyperdb').debug("opendb %r.open(%r, %r)"%(db_type, path,
                mode))
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
        # we'll be supplied these props if we're doing an import
        if not node.has_key('creator'):
            # add in the "calculated" properties (dupe so we don't affect
            # calling code's node assumptions)
            node = node.copy()
            node['creator'] = self.getuid()
            node['actor'] = self.getuid()
            node['creation'] = node['activity'] = date.Date()

        self.newnodes.setdefault(classname, {})[nodeid] = 1
        self.cache.setdefault(classname, {})[nodeid] = node
        self.savenode(classname, nodeid, node)

    def setnode(self, classname, nodeid, node):
        ''' change the specified node
        '''
        self.dirtynodes.setdefault(classname, {})[nodeid] = 1

        # can't set without having already loaded the node
        self.cache[classname][nodeid] = node
        self.savenode(classname, nodeid, node)

    def savenode(self, classname, nodeid, node):
        ''' perform the saving of data specified by the set/addnode
        '''
        if __debug__:
            logging.getLogger('hyperdb').debug('save %s%s %r'%(classname, nodeid, node))
        self.transactions.append((self.doSaveNode, (classname, nodeid, node)))

    def getnode(self, classname, nodeid, db=None, cache=1):
        ''' get a node from the database

            Note the "cache" parameter is not used, and exists purely for
            backward compatibility!
        '''
        # try the cache
        cache_dict = self.cache.setdefault(classname, {})
        if cache_dict.has_key(nodeid):
            if __debug__:
                logging.getLogger('hyperdb').debug('get %s%s cached'%(classname, nodeid))
                self.stats['cache_hits'] += 1
            return cache_dict[nodeid]

        if __debug__:
            self.stats['cache_misses'] += 1
            start_t = time.time()
            logging.getLogger('hyperdb').debug('get %s%s'%(classname, nodeid))

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

        if __debug__:
            self.stats['get_items'] += (time.time() - start_t)

        return res

    def destroynode(self, classname, nodeid):
        '''Remove a node from the database. Called exclusively by the
           destroy() method on Class.
        '''
        logging.getLogger('hyperdb').info('destroy %s%s'%(classname, nodeid))

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
        properties = self.getclass(classname).getprops()
        d = {}
        for k, v in node.items():
            if k == self.RETIRED_FLAG:
                d[k] = v
                continue

            # if the property doesn't exist then we really don't care
            if not properties.has_key(k):
                continue

            # get the property spec
            prop = properties[k]

            if isinstance(prop, hyperdb.Password) and v is not None:
                d[k] = str(v)
            elif isinstance(prop, hyperdb.Date) and v is not None:
                d[k] = v.serialise()
            elif isinstance(prop, hyperdb.Interval) and v is not None:
                d[k] = v.serialise()
            else:
                d[k] = v
        return d

    def unserialise(self, classname, node):
        '''Decode the marshalled node data
        '''
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

            if isinstance(prop, hyperdb.Date) and v is not None:
                d[k] = date.Date(v)
            elif isinstance(prop, hyperdb.Interval) and v is not None:
                d[k] = date.Interval(v)
            elif isinstance(prop, hyperdb.Password) and v is not None:
                p = password.Password()
                p.unpack(v)
                d[k] = p
            else:
                d[k] = v
        return d

    def hasnode(self, classname, nodeid, db=None):
        ''' determine if the database has a given node
        '''
        # try the cache
        cache = self.cache.setdefault(classname, {})
        if cache.has_key(nodeid):
            return 1

        # not in the cache - check the database
        if db is None:
            db = self.getclassdb(classname)
        res = db.has_key(nodeid)
        return res

    def countnodes(self, classname, db=None):
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

            'creator' -- the user performing the action, which defaults to
            the current user.
        '''
        if __debug__:
            logging.getLogger('hyperdb').debug('addjournal %s%s %s %r %s %r'%(classname,
                nodeid, action, params, creator, creation))
        if creator is None:
            creator = self.getuid()
        self.transactions.append((self.doSaveJournal, (classname, nodeid,
            action, params, creator, creation)))

    def setjournal(self, classname, nodeid, journal):
        '''Set the journal to the "journal" list.'''
        if __debug__:
            logging.getLogger('hyperdb').debug('setjournal %s%s %r'%(classname,
                nodeid, journal))
        self.transactions.append((self.doSetJournal, (classname, nodeid,
            journal)))

    def getjournal(self, classname, nodeid):
        ''' get the journal for id

            Raise IndexError if the node doesn't exist (as per history()'s
            API)
        '''
        # our journal result
        res = []

        # add any journal entries for transactions not committed to the
        # database
        for method, args in self.transactions:
            if method != self.doSaveJournal:
                continue
            (cache_classname, cache_nodeid, cache_action, cache_params,
                cache_creator, cache_creation) = args
            if cache_classname == classname and cache_nodeid == nodeid:
                if not cache_creator:
                    cache_creator = self.getuid()
                if not cache_creation:
                    cache_creation = date.Date()
                res.append((cache_nodeid, cache_creation, cache_creator,
                    cache_action, cache_params))

        # attempt to open the journal - in some rare cases, the journal may
        # not exist
        try:
            db = self.opendb('journals.%s'%classname, 'r')
        except anydbm.error, error:
            if str(error) == "need 'c' or 'n' flag to open new db":
                raise IndexError, 'no such %s %s'%(classname, nodeid)
            elif error.args[0] != 2:
                # this isn't a "not found" error, be alarmed!
                raise
            if res:
                # we have unsaved journal entries, return them
                return res
            raise IndexError, 'no such %s %s'%(classname, nodeid)
        try:
            journal = marshal.loads(db[nodeid])
        except KeyError:
            db.close()
            if res:
                # we have some unsaved journal entries, be happy!
                return res
            raise IndexError, 'no such %s %s'%(classname, nodeid)
        db.close()

        # add all the saved journal entries for this node
        for nodeid, date_stamp, user, action, params in journal:
            res.append((nodeid, date.Date(date_stamp), user, action, params))
        return res

    def pack(self, pack_before):
        ''' Delete all journal entries except "create" before 'pack_before'.
        '''
        pack_before = pack_before.serialise()
        for classname in self.getclasses():
            packed = 0
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
                    else:
                        packed += 1
                db[key] = marshal.dumps(l)

                logging.getLogger('hyperdb').info('packed %d %s items'%(packed,
                    classname))

            if db_type == 'gdbm':
                db.reorganize()
            db.close()


    #
    # Basic transaction support
    #
    def commit(self, fail_ok=False):
        ''' Commit the current transactions.

        Save all data changed since the database was opened or since the
        last commit() or rollback().

        fail_ok indicates that the commit is allowed to fail. This is used
        in the web interface when committing cleaning of the session
        database. We don't care if there's a concurrency issue there.

        The only backend this seems to affect is postgres.
        '''
        logging.getLogger('hyperdb').info('commit %s transactions'%(
            len(self.transactions)))

        # keep a handle to all the database files opened
        self.databases = {}

        try:
            # now, do all the transactions
            reindex = {}
            for method, args in self.transactions:
                reindex[method(*args)] = 1
        finally:
            # make sure we close all the database files
            for db in self.databases.values():
                db.close()
            del self.databases

        # reindex the nodes that request it
        for classname, nodeid in filter(None, reindex.keys()):
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
        journaltag = creator
        if creation:
            journaldate = creation.serialise()
        else:
            journaldate = date.Date().serialise()

        # create the journal entry
        entry = (nodeid, journaldate, journaltag, action, params)

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

    def doSetJournal(self, classname, nodeid, journal):
        l = []
        for nodeid, journaldate, journaltag, action, params in journal:
            # serialise the parameters now if necessary
            if isinstance(params, type({})):
                if action in ('set', 'create'):
                    params = self.serialise(classname, params)
            journaldate = journaldate.serialise()
            l.append((nodeid, journaldate, journaltag, action, params))
        db = self.getCachedJournalDB(classname)
        db[nodeid] = marshal.dumps(l)

    def doDestroyNode(self, classname, nodeid):
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
        logging.getLogger('hyperdb').info('rollback %s transactions'%(
            len(self.transactions)))

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
            self.lockfile.close()
            self.lockfile = None

_marker = []
class Class(hyperdb.Class):
    '''The handle to a particular class of nodes in a hyperdatabase.'''

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
        self.fireAuditors('create', None, propvalues)
        newid = self.create_inner(**propvalues)
        self.fireReactors('create', newid, None)
        return newid

    def create_inner(self, **propvalues):
        ''' Called by create, in-between the audit and react calls.
        '''
        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'

        if self.db.journaltag is None:
            raise hyperdb.DatabaseError, 'Database open read-only'

        if propvalues.has_key('creation') or propvalues.has_key('activity'):
            raise KeyError, '"creation" and "activity" are reserved'
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

            if value is not None and isinstance(prop, hyperdb.Link):
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

            elif isinstance(prop, hyperdb.Multilink):
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

            elif isinstance(prop, hyperdb.String):
                if type(value) != type('') and type(value) != type(u''):
                    raise TypeError, 'new property "%s" not a string'%key
                if prop.indexme:
                    self.db.indexer.add_text((self.classname, newid, key),
                        value)

            elif isinstance(prop, hyperdb.Password):
                if not isinstance(value, password.Password):
                    raise TypeError, 'new property "%s" not a Password'%key

            elif isinstance(prop, hyperdb.Date):
                if value is not None and not isinstance(value, date.Date):
                    raise TypeError, 'new property "%s" not a Date'%key

            elif isinstance(prop, hyperdb.Interval):
                if value is not None and not isinstance(value, date.Interval):
                    raise TypeError, 'new property "%s" not an Interval'%key

            elif value is not None and isinstance(prop, hyperdb.Number):
                try:
                    float(value)
                except ValueError:
                    raise TypeError, 'new property "%s" not numeric'%key

            elif value is not None and isinstance(prop, hyperdb.Boolean):
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
            if isinstance(prop, hyperdb.Multilink):
                propvalues[key] = []

        # done
        self.db.addnode(self.classname, newid, propvalues)
        if self.do_journal:
            self.db.addjournal(self.classname, newid, 'create', {})

        return newid

    def get(self, nodeid, propname, default=_marker, cache=1):
        '''Get the value of a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.  'propname' must be the name of a property
        of this class or a KeyError is raised.

        'cache' exists for backward compatibility, and is not used.

        Attempts to get the "creation" or "activity" properties should
        do the right thing.
        '''
        if propname == 'id':
            return nodeid

        # get the node's dict
        d = self.db.getnode(self.classname, nodeid)

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
                value = journal[0][2]
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
                return self.db.getuid()
        if propname == 'actor':
            if d.has_key('actor'):
                return d['actor']
            if not self.do_journal:
                raise ValueError, 'Journalling is disabled for this class'
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                num_re = re.compile('^\d+$')
                value = journal[-1][2]
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
                return self.db.getuid()

        # get the property (raises KeyErorr if invalid)
        prop = self.properties[propname]

        if not d.has_key(propname):
            if default is _marker:
                if isinstance(prop, hyperdb.Multilink):
                    return []
                else:
                    return None
            else:
                return default

        # return a dupe of the list so code doesn't get confused
        if isinstance(prop, hyperdb.Multilink):
            return d[propname][:]

        return d[propname]

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
        self.fireAuditors('set', nodeid, propvalues)
        oldvalues = copy.deepcopy(self.db.getnode(self.classname, nodeid))
        for name,prop in self.getprops(protected=0).items():
            if oldvalues.has_key(name):
                continue
            if isinstance(prop, hyperdb.Multilink):
                oldvalues[name] = []
            else:
                oldvalues[name] = None
        propvalues = self.set_inner(nodeid, **propvalues)
        self.fireReactors('set', nodeid, oldvalues)
        return propvalues

    def set_inner(self, nodeid, **propvalues):
        ''' Called by set, in-between the audit and react calls.
        '''
        if not propvalues:
            return propvalues

        if propvalues.has_key('creation') or propvalues.has_key('activity'):
            raise KeyError, '"creation" and "activity" are reserved'

        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'

        if self.db.journaltag is None:
            raise hyperdb.DatabaseError, 'Database open read-only'

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
            if isinstance(prop, hyperdb.Link):
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

            elif isinstance(prop, hyperdb.Multilink):
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

            elif isinstance(prop, hyperdb.String):
                if value is not None and type(value) != type('') and type(value) != type(u''):
                    raise TypeError, 'new property "%s" not a string'%propname
                if prop.indexme:
                    self.db.indexer.add_text((self.classname, nodeid, propname),
                        value)

            elif isinstance(prop, hyperdb.Password):
                if not isinstance(value, password.Password):
                    raise TypeError, 'new property "%s" not a Password'%propname
                propvalues[propname] = value

            elif value is not None and isinstance(prop, hyperdb.Date):
                if not isinstance(value, date.Date):
                    raise TypeError, 'new property "%s" not a Date'% propname
                propvalues[propname] = value

            elif value is not None and isinstance(prop, hyperdb.Interval):
                if not isinstance(value, date.Interval):
                    raise TypeError, 'new property "%s" not an '\
                        'Interval'%propname
                propvalues[propname] = value

            elif value is not None and isinstance(prop, hyperdb.Number):
                try:
                    float(value)
                except ValueError:
                    raise TypeError, 'new property "%s" not numeric'%propname

            elif value is not None and isinstance(prop, hyperdb.Boolean):
                try:
                    int(value)
                except ValueError:
                    raise TypeError, 'new property "%s" not boolean'%propname

            node[propname] = value

        # nothing to do?
        if not propvalues:
            return propvalues

        # update the activity time
        node['activity'] = date.Date()
        node['actor'] = self.db.getuid()

        # do the set, and journal it
        self.db.setnode(self.classname, nodeid, node)

        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, 'set', journalvalues)

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
            raise hyperdb.DatabaseError, 'Database open read-only'

        self.fireAuditors('retire', nodeid, None)

        node = self.db.getnode(self.classname, nodeid)
        node[self.db.RETIRED_FLAG] = 1
        self.db.setnode(self.classname, nodeid, node)
        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, 'retired', None)

        self.fireReactors('retire', nodeid, None)

    def restore(self, nodeid):
        '''Restpre a retired node.

        Make node available for all operations like it was before retirement.
        '''
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError, 'Database open read-only'

        node = self.db.getnode(self.classname, nodeid)
        # check if key property was overrided
        key = self.getkey()
        try:
            id = self.lookup(node[key])
        except KeyError:
            pass
        else:
            raise KeyError, "Key property (%s) of retired node clashes with \
                existing one (%s)" % (key, node[key])
        # Now we can safely restore node
        self.fireAuditors('restore', nodeid, None)
        del node[self.db.RETIRED_FLAG]
        self.db.setnode(self.classname, nodeid, node)
        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, 'restored', None)

        self.fireReactors('restore', nodeid, None)

    def is_retired(self, nodeid, cldb=None):
        '''Return true if the node is retired.
        '''
        node = self.db.getnode(self.classname, nodeid, cldb)
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
            raise hyperdb.DatabaseError, 'Database open read-only'
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
        if not isinstance(prop, hyperdb.String):
            raise TypeError, 'key properties must be String'
        self.key = propname

    def getkey(self):
        '''Return the name of the key property for this class or None.'''
        return self.key

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
            for nodeid in self.getnodeids(cldb):
                node = self.db.getnode(self.classname, nodeid, cldb)
                if node.has_key(self.db.RETIRED_FLAG):
                    continue
                if not node.has_key(self.key):
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

        Any node in this class whose 'propname' property links to any of
        the nodeids will be returned. Examples::

            db.issue.find(messages='1')
            db.issue.find(messages={'1':1,'3':1}, files={'7':1})
        '''
        propspec = propspec.items()
        for propname, itemids in propspec:
            # check the prop is OK
            prop = self.properties[propname]
            if not isinstance(prop, hyperdb.Link) and not isinstance(prop, hyperdb.Multilink):
                raise TypeError, "'%s' not a Link/Multilink property"%propname

        # ok, now do the find
        cldb = self.db.getclassdb(self.classname)
        l = []
        try:
            for id in self.getnodeids(db=cldb):
                item = self.db.getnode(self.classname, id, db=cldb)
                if item.has_key(self.db.RETIRED_FLAG):
                    continue
                for propname, itemids in propspec:
                    if type(itemids) is not type({}):
                        itemids = {itemids:1}

                    # special case if the item doesn't have this property
                    if not item.has_key(propname):
                        if itemids.has_key(None):
                            l.append(id)
                            break
                        continue

                    # grab the property definition and its value on this item
                    prop = self.properties[propname]
                    value = item[propname]
                    if isinstance(prop, hyperdb.Link) and itemids.has_key(value):
                        l.append(id)
                        break
                    elif isinstance(prop, hyperdb.Multilink):
                        hit = 0
                        for v in value:
                            if itemids.has_key(v):
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
            if not isinstance(prop, hyperdb.String):
                raise TypeError, "'%s' not a String property"%propname
            requirements[propname] = requirements[propname].lower()
        l = []
        cldb = self.db.getclassdb(self.classname)
        try:
            for nodeid in self.getnodeids(cldb):
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
            for nodeid in self.getnodeids(cldb):
                node = self.db.getnode(cn, nodeid, cldb)
                if node.has_key(self.db.RETIRED_FLAG):
                    continue
                l.append(nodeid)
        finally:
            cldb.close()
        l.sort()
        return l

    def getnodeids(self, db=None, retired=None):
        ''' Return a list of ALL nodeids

            Set retired=None to get all nodes. Otherwise it'll get all the
            retired or non-retired nodes, depending on the flag.
        '''
        res = []

        # start off with the new nodes
        if self.db.newnodes.has_key(self.classname):
            res += self.db.newnodes[self.classname].keys()

        must_close = False
        if db is None:
            db = self.db.getclassdb(self.classname)
            must_close = True 
        try:
            res = res + db.keys()

            # remove the uncommitted, destroyed nodes
            if self.db.destroyednodes.has_key(self.classname):
                for nodeid in self.db.destroyednodes[self.classname].keys():
                    if db.has_key(nodeid):
                        res.remove(nodeid)

            # check retired flag
            if retired is False or retired is True:
                l = []
                for nodeid in res:
                    node = self.db.getnode(self.classname, nodeid, db)
                    is_ret = node.has_key(self.db.RETIRED_FLAG)
                    if retired == is_ret:
                        l.append(nodeid)
                res = l
        finally:
            if must_close:
                db.close()
        return res

    def _filter(self, search_matches, filterspec, proptree,
            num_re = re.compile('^\d+$')):
        """Return a list of the ids of the active nodes in this class that
        match the 'filter' spec, sorted by the group spec and then the
        sort spec.

        "filterspec" is {propname: value(s)}

        "sort" and "group" are (dir, prop) where dir is '+', '-' or None
        and prop is a prop name or None

        "search_matches" is {nodeid: marker} or None

        The filter must match all properties specificed. If the property
        value to match is a list:
        
        1. String properties must match all elements in the list, and
        2. Other properties must match any of the elements in the list.
        """
        if __debug__:
            start_t = time.time()

        cn = self.classname

        # optimise filterspec
        l = []
        props = self.getprops()
        LINK = 'spec:link'
        MULTILINK = 'spec:multilink'
        STRING = 'spec:string'
        DATE = 'spec:date'
        INTERVAL = 'spec:interval'
        OTHER = 'spec:other'

        for k, v in filterspec.items():
            propclass = props[k]
            if isinstance(propclass, hyperdb.Link):
                if type(v) is not type([]):
                    v = [v]
                u = []
                for entry in v:
                    # the value -1 is a special "not set" sentinel
                    if entry == '-1':
                        entry = None
                    u.append(entry)
                l.append((LINK, k, u))
            elif isinstance(propclass, hyperdb.Multilink):
                # the value -1 is a special "not set" sentinel
                if v in ('-1', ['-1']):
                    v = []
                elif type(v) is not type([]):
                    v = [v]
                l.append((MULTILINK, k, v))
            elif isinstance(propclass, hyperdb.String) and k != 'id':
                if type(v) is not type([]):
                    v = [v]
                for v in v:
                    # simple glob searching
                    v = re.sub(r'([\|\{\}\\\.\+\[\]\(\)])', r'\\\1', v)
                    v = v.replace('?', '.')
                    v = v.replace('*', '.*?')
                    l.append((STRING, k, re.compile(v, re.I)))
            elif isinstance(propclass, hyperdb.Date):
                try:
                    date_rng = propclass.range_from_raw(v, self.db)
                    l.append((DATE, k, date_rng))
                except ValueError:
                    # If range creation fails - ignore that search parameter
                    pass
            elif isinstance(propclass, hyperdb.Interval):
                try:
                    intv_rng = date.Range(v, date.Interval)
                    l.append((INTERVAL, k, intv_rng))
                except ValueError:
                    # If range creation fails - ignore that search parameter
                    pass

            elif isinstance(propclass, hyperdb.Boolean):
                if type(v) != type([]):
                    v = v.split(',')
                bv = []
                for val in v:
                    if type(val) is type(''):
                        bv.append(val.lower() in ('yes', 'true', 'on', '1'))
                    else:
                        bv.append(val)
                l.append((OTHER, k, bv))

            elif k == 'id':
                if type(v) != type([]):
                    v = v.split(',')
                l.append((OTHER, k, [str(int(val)) for val in v]))

            elif isinstance(propclass, hyperdb.Number):
                if type(v) != type([]):
                    v = v.split(',')
                l.append((OTHER, k, [float(val) for val in v]))

        filterspec = l

        # now, find all the nodes that are active and pass filtering
        matches = []
        cldb = self.db.getclassdb(cn)
        t = 0
        try:
            # TODO: only full-scan once (use items())
            for nodeid in self.getnodeids(cldb):
                node = self.db.getnode(cn, nodeid, cldb)
                if node.has_key(self.db.RETIRED_FLAG):
                    continue
                # apply filter
                for t, k, v in filterspec:
                    # handle the id prop
                    if k == 'id':
                        if nodeid not in v:
                            break
                        continue

                    # get the node value
                    nv = node.get(k, None)

                    match = 0

                    # now apply the property filter
                    if t == LINK:
                        # link - if this node's property doesn't appear in the
                        # filterspec's nodeid list, skip it
                        match = nv in v
                    elif t == MULTILINK:
                        # multilink - if any of the nodeids required by the
                        # filterspec aren't in this node's property, then skip
                        # it
                        nv = node.get(k, [])

                        # check for matching the absence of multilink values
                        if not v:
                            match = not nv
                        else:
                            # othewise, make sure this node has each of the
                            # required values
                            for want in v:
                                if want in nv:
                                    match = 1
                                    break
                    elif t == STRING:
                        if nv is None:
                            nv = ''
                        # RE search
                        match = v.search(nv)
                    elif t == DATE or t == INTERVAL:
                        if nv is None:
                            match = v is None
                        else:
                            if v.to_value:
                                if v.from_value <= nv and v.to_value >= nv:
                                    match = 1
                            else:
                                if v.from_value <= nv:
                                    match = 1
                    elif t == OTHER:
                        # straight value comparison for the other types
                        match = nv in v
                    if not match:
                        break
                else:
                    matches.append([nodeid, node])

            # filter based on full text search
            if search_matches is not None:
                k = []
                for v in matches:
                    if search_matches.has_key(v[0]):
                        k.append(v)
                matches = k

            # add sorting information to the proptree
            JPROPS = {'actor':1, 'activity':1, 'creator':1, 'creation':1}
            children = []
            if proptree:
                children = proptree.sortable_children()
            for pt in children:
                dir = pt.sort_direction
                prop = pt.name
                assert (dir and prop)
                propclass = props[prop]
                pt.sort_ids = []
                is_pointer = isinstance(propclass,(hyperdb.Link,
                    hyperdb.Multilink))
                if not is_pointer:
                    pt.sort_result = []
                try:
                    # cache the opened link class db, if needed.
                    lcldb = None
                    # cache the linked class items too
                    lcache = {}

                    for entry in matches:
                        itemid = entry[-2]
                        item = entry[-1]
                        # handle the properties that might be "faked"
                        # also, handle possible missing properties
                        try:
                            v = item[prop]
                        except KeyError:
                            if JPROPS.has_key(prop):
                                # force lookup of the special journal prop
                                v = self.get(itemid, prop)
                            else:
                                # the node doesn't have a value for this
                                # property
                                v = None
                                if isinstance(propclass, hyperdb.Multilink):
                                    v = []
                                if prop == 'id':
                                    v = int (itemid)
                                pt.sort_ids.append(v)
                                if not is_pointer:
                                    pt.sort_result.append(v)
                                continue

                        # missing (None) values are always sorted first
                        if v is None:
                            pt.sort_ids.append(v)
                            if not is_pointer:
                                pt.sort_result.append(v)
                            continue

                        if isinstance(propclass, hyperdb.Link):
                            lcn = propclass.classname
                            link = self.db.classes[lcn]
                            key = link.orderprop()
                            child = pt.propdict[key]
                            if key!='id':
                                if not lcache.has_key(v):
                                    # open the link class db if it's not already
                                    if lcldb is None:
                                        lcldb = self.db.getclassdb(lcn)
                                    lcache[v] = self.db.getnode(lcn, v, lcldb)
                                r = lcache[v][key]
                                child.propdict[key].sort_ids.append(r)
                            else:
                                child.propdict[key].sort_ids.append(v)
                        pt.sort_ids.append(v)
                        if not is_pointer:
                            r = propclass.sort_repr(pt.parent.cls, v, pt.name)
                            pt.sort_result.append(r)
                finally:
                    # if we opened the link class db, close it now
                    if lcldb is not None:
                        lcldb.close()
                del lcache
        finally:
            cldb.close()

        # pull the id out of the individual entries
        matches = [entry[-2] for entry in matches]
        if __debug__:
            self.db.stats['filtering'] += (time.time() - start_t)
        return matches

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
            d['id'] = hyperdb.String()
            d['creation'] = hyperdb.Date()
            d['activity'] = hyperdb.Date()
            d['creator'] = hyperdb.Link('user')
            d['actor'] = hyperdb.Link('user')
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
        ''' Add (or refresh) the node to search indexes '''
        # find all the String properties that have indexme
        for prop, propclass in self.getprops().items():
            if isinstance(propclass, hyperdb.String) and propclass.indexme:
                # index them under (classname, nodeid, property)
                try:
                    value = str(self.get(nodeid, prop))
                except IndexError:
                    # node has been destroyed
                    continue
                self.db.indexer.add_text((self.classname, nodeid, prop), value)

    #
    # import / export support
    #
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

        # append retired flag
        l.append(repr(self.is_retired(nodeid)))

        return l

    def import_list(self, propnames, proplist):
        ''' Import a node - all information including "id" is present and
            should not be sanity checked. Triggers are not triggered. The
            journal should be initialised using the "creator" and "created"
            information.

            Return the nodeid of the node imported.
        '''
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError, 'Database open read-only'
        properties = self.getprops()

        # make the new node's property map
        d = {}
        newid = None
        for i in range(len(propnames)):
            # Figure the property for this column
            propname = propnames[i]

            # Use eval to reverse the repr() used to output the CSV
            value = eval(proplist[i])

            # "unmarshal" where necessary
            if propname == 'id':
                newid = value
                continue
            elif propname == 'is retired':
                # is the item retired?
                if int(value):
                    d[self.db.RETIRED_FLAG] = 1
                continue
            elif value is None:
                d[propname] = None
                continue

            prop = properties[propname]
            if isinstance(prop, hyperdb.Date):
                value = date.Date(value)
            elif isinstance(prop, hyperdb.Interval):
                value = date.Interval(value)
            elif isinstance(prop, hyperdb.Password):
                pwd = password.Password()
                pwd.unpack(value)
                value = pwd
            d[propname] = value

        # get a new id if necessary
        if newid is None:
            newid = self.db.newid(self.classname)

        # add the node and journal
        self.db.addnode(self.classname, newid, d)
        return newid

    def export_journals(self):
        '''Export a class's journal - generate a list of lists of
        CSV-able data:

            nodeid, date, user, action, params

        No heading here - the columns are fixed.
        '''
        properties = self.getprops()
        r = []
        for nodeid in self.getnodeids():
            for nodeid, date, user, action, params in self.history(nodeid):
                date = date.get_tuple()
                if action == 'set':
                    export_data = {}
                    for propname, value in params.items():
                        if not properties.has_key(propname):
                            # property no longer in the schema
                            continue

                        prop = properties[propname]
                        # make sure the params are eval()'able
                        if value is None:
                            # don't export empties
                            continue
                        elif isinstance(prop, hyperdb.Date):
                            # this is a hack - some dates are stored as strings
                            if not isinstance(value, type('')):
                                value = value.get_tuple()
                        elif isinstance(prop, hyperdb.Interval):
                            # hack too - some intervals are stored as strings
                            if not isinstance(value, type('')):
                                value = value.get_tuple()
                        elif isinstance(prop, hyperdb.Password):
                            value = str(value)
                        export_data[propname] = value
                    params = export_data
                l = [nodeid, date, user, action, params]
                r.append(map(repr, l))
        return r

    def import_journals(self, entries):
        '''Import a class's journal.

        Uses setjournal() to set the journal for each item.'''
        properties = self.getprops()
        d = {}
        for l in entries:
            l = map(eval, l)
            nodeid, jdate, user, action, params = l
            r = d.setdefault(nodeid, [])
            if action == 'set':
                for propname, value in params.items():
                    prop = properties[propname]
                    if value is None:
                        pass
                    elif isinstance(prop, hyperdb.Date):
                        if type(value) == type(()):
                            print _('WARNING: invalid date tuple %r')%(value,)
                            value = date.Date( "2000-1-1" )
                        value = date.Date(value)
                    elif isinstance(prop, hyperdb.Interval):
                        value = date.Interval(value)
                    elif isinstance(prop, hyperdb.Password):
                        pwd = password.Password()
                        pwd.unpack(value)
                        value = pwd
                    params[propname] = value
            r.append((nodeid, date.Date(jdate), user, action, params))

        for nodeid, l in d.items():
            self.db.setjournal(self.classname, nodeid, l)

class FileClass(hyperdb.FileClass, Class):
    '''This class defines a large chunk of data. To support this, it has a
       mandatory String property "content" which is typically saved off
       externally to the hyperdb.

       The default MIME type of this data is defined by the
       "default_mime_type" class attribute, which may be overridden by each
       node if the class defines a "type" String property.
    '''
    def __init__(self, db, classname, **properties):
        '''The newly-created class automatically includes the "content"
        and "type" properties.
        '''
        if not properties.has_key('content'):
            properties['content'] = hyperdb.String(indexme='yes')
        if not properties.has_key('type'):
            properties['type'] = hyperdb.String()
        Class.__init__(self, db, classname, **properties)

    def create(self, **propvalues):
        ''' Snarf the "content" propvalue and store in a file
        '''
        # we need to fire the auditors now, or the content property won't
        # be in propvalues for the auditors to play with
        self.fireAuditors('create', None, propvalues)

        # now remove the content property so it's not stored in the db
        content = propvalues['content']
        del propvalues['content']

        # make sure we have a MIME type
        mime_type = propvalues.get('type', self.default_mime_type)

        # do the database create
        newid = self.create_inner(**propvalues)

        # fire reactors
        self.fireReactors('create', newid, None)

        # store off the content as a file
        self.db.storefile(self.classname, newid, None, content)
        return newid

    def get(self, nodeid, propname, default=_marker, cache=1):
        ''' Trap the content propname and get it from the file

        'cache' exists for backwards compatibility, and is not used.
        '''
        poss_msg = 'Possibly an access right configuration problem.'
        if propname == 'content':
            try:
                return self.db.getfile(self.classname, nodeid, None)
            except IOError, (strerror):
                # XXX by catching this we don't see an error in the log.
                return 'ERROR reading file: %s%s\n%s\n%s'%(
                        self.classname, nodeid, poss_msg, strerror)
        if default is not _marker:
            return Class.get(self, nodeid, propname, default)
        else:
            return Class.get(self, nodeid, propname)

    def set(self, itemid, **propvalues):
        ''' Snarf the "content" propvalue and update it in a file
        '''
        self.fireAuditors('set', itemid, propvalues)

        # create the oldvalues dict - fill in any missing values
        oldvalues = copy.deepcopy(self.db.getnode(self.classname, itemid))
        for name,prop in self.getprops(protected=0).items():
            if oldvalues.has_key(name):
                continue
            if isinstance(prop, hyperdb.Multilink):
                oldvalues[name] = []
            else:
                oldvalues[name] = None

        # now remove the content property so it's not stored in the db
        content = None
        if propvalues.has_key('content'):
            content = propvalues['content']
            del propvalues['content']

        # do the database update
        propvalues = self.set_inner(itemid, **propvalues)

        # do content?
        if content:
            # store and possibly index
            self.db.storefile(self.classname, itemid, None, content)
            if self.properties['content'].indexme:
                mime_type = self.get(itemid, 'type', self.default_mime_type)
                self.db.indexer.add_text((self.classname, itemid, 'content'),
                    content, mime_type)
            propvalues['content'] = content

        # fire reactors
        self.fireReactors('set', itemid, oldvalues)
        return propvalues

    def index(self, nodeid):
        ''' Add (or refresh) the node to search indexes.

        Use the content-type property for the content property.
        '''
        # find all the String properties that have indexme
        for prop, propclass in self.getprops().items():
            if prop == 'content' and propclass.indexme:
                mime_type = self.get(nodeid, 'type', self.default_mime_type)
                self.db.indexer.add_text((self.classname, nodeid, 'content'),
                    str(self.get(nodeid, 'content')), mime_type)
            elif isinstance(propclass, hyperdb.String) and propclass.indexme:
                # index them under (classname, nodeid, property)
                try:
                    value = str(self.get(nodeid, prop))
                except IndexError:
                    # node has been destroyed
                    continue
                self.db.indexer.add_text((self.classname, nodeid, prop), value)

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

# vim: set et sts=4 sw=4 :
