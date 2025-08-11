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
"""This module defines a backend that saves the hyperdatabase in a
database chosen by anydbm. It is guaranteed to always be available in python
versions >2.1.1 (the dumbdbm fallback in 2.1.1 and earlier has several
serious bugs, and is not available)
"""
__docformat__ = 'restructuredtext'

import copy
import logging
import marshal
import os
import re
import shutil
import time

from roundup.anypy.dbm_ import anydbm, whichdb
from roundup.anypy.strings import b2s, repr_export, eval_import, is_us

from roundup import hyperdb, date, password, roundupdb, security, support
from roundup.mlink_expr import Expression, ExpressionError
from roundup.backends import locking
from roundup.i18n import _

from roundup.backends.blobfiles import FileStorage
from roundup.backends import sessions_dbm

try:
    from roundup.backends import sessions_redis
except ImportError:
    sessions_redis = None

from roundup.backends.indexer_common import get_indexer


def db_exists(config):
    # check for the user db
    for db in 'nodes.user nodes.user.db nodes.user.dat'.split():
        if os.path.exists(os.path.join(config.DATABASE, db)):
            return 1
    return 0


def db_nuke(config):
    shutil.rmtree(config.DATABASE)


# python 3 doesn't have a unicode type
try:
    unicode  # noqa: F821
except NameError:
    unicode = str


# marker used for an unspecified keyword argument
_marker = []


#
# Now the database
#


class Database(FileStorage, hyperdb.Database, roundupdb.Database):
    """A database for storing records containing flexible data types.

    Transaction stuff TODO:

    - check the timestamp of the class file and nuke the cache if it's
      modified. Do some sort of conflict checking on the dirty stuff.
    - perhaps detect write collisions (related to above)?

    attributes:
      dbtype:
        holds the value for the type of db. It is used by indexer to
        identify the database type so it can import the correct indexer
        module when using native text search mode.
    """

    dbtype = "anydbm"

    # used by migrate roundup_admin command. Is a no-op for anydbm.
    # but needed to stop traceback in admin.
    db_version_updated = False

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
        Class.set(), Class.retire(), and Class.restore() methods are
        disabled.
        """
        FileStorage.__init__(self, config.UMASK)
        roundupdb.Database.__init__(self)
        self.config, self.journaltag = config, journaltag
        self.dir = config.DATABASE
        self.classes = {}
        self.cache = {}         # cache of nodes loaded or created
        self.stats = {'cache_hits': 0, 'cache_misses': 0, 'get_items': 0,
                      'filtering': 0}
        self.dirtynodes = {}      # keep track of the dirty nodes by class
        self.newnodes = {}        # keep track of the new nodes by class
        self.destroyednodes = {}  # keep track of the destroyed nodes by class
        self.transactions = []
        self.indexer = get_indexer(config, self)
        self.security = security.Security(self)
        os.umask(config.UMASK)

        # make sure the database directory exists
        if not os.path.isdir(self.config.DATABASE):
            os.makedirs(self.config.DATABASE)

        # lock it
        lockfilenm = os.path.join(self.dir, 'lock')
        self.lockfile = locking.acquire_lock(lockfilenm)
        self.lockfile.write(str(os.getpid()))
        self.lockfile.flush()

        self.Session = None
        self.Otk = None

    def post_init(self):
        """Called once the schema initialisation has finished.
        """
        super(Database, self).post_init()
        # reindex the db if necessary
        if self.indexer.should_reindex():
            self.reindex()

    def refresh_database(self):
        """Rebuild the database
        """
        self.reindex()

    def getSessionManager(self):
        if not self.Session:
            if self.config.SESSIONDB_BACKEND == "redis":
                if sessions_redis is None:
                    self.Session = sessions_dbm.Sessions(self)
                    raise ValueError("[redis] session is set, but "
                                     "redis is not found")
                self.Session = sessions_redis.Sessions(self)
            else:
                self.Session = sessions_dbm.Sessions(self)
        return self.Session

    def getOTKManager(self):
        if not self.Otk:
            if self.config.SESSIONDB_BACKEND == "redis":
                if sessions_redis is None:
                    self.Session = sessions_dbm.OneTimeKeys(self)
                    raise ValueError("[redis] session is set, but "
                                     "redis is not found")
                self.Otk = sessions_redis.OneTimeKeys(self)
            else:
                self.Otk = sessions_dbm.OneTimeKeys(self)
        return self.Otk

    def reindex(self, classname=None, show_progress=False):
        if classname:
            classes = [self.getclass(classname)]
        else:
            classes = self.classes.values()
        for klass in classes:
            if show_progress:
                for nodeid in support.Progress('Reindex %s' %
                                               klass.classname, klass.list()):
                    klass.index(nodeid)
            else:
                for nodeid in klass.list():
                    klass.index(nodeid)
        self.indexer.save_index()

    def __repr__(self):
        return '<back_anydbm instance at %x>' % id(self)

    #
    # Classes
    #
    def __getattr__(self, classname):
        """A convenient way of calling self.getclass(classname)."""
        if classname in self.classes:
            return self.classes[classname]
        raise AttributeError(classname)

    def addclass(self, cl):
        cn = cl.classname
        if cn in self.classes:
            raise ValueError(_('Class "%s" already defined.') % cn)
        self.classes[cn] = cl

        # add default Edit and View permissions
        self.security.addPermission(
            name="Create", klass=cn,
            description="User is allowed to create "+cn)
        self.security.addPermission(
            name="Edit", klass=cn,
            description="User is allowed to edit "+cn)
        self.security.addPermission(
            name="View", klass=cn,
            description="User is allowed to access "+cn)
        self.security.addPermission(
            name="Retire", klass=cn,
            description="User is allowed to retire "+cn)

    def getclasses(self):
        """Return a list of the names of all existing classes."""
        return sorted(self.classes.keys())

    def getclass(self, classname):
        """Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        """
        try:
            return self.classes[classname]
        except KeyError:
            raise KeyError('There is no class called "%s"' % classname)

    #
    # Class DBs
    #
    def clear(self):
        """Delete all database contents
        """
        logging.getLogger('roundup.hyperdb.backend').info('clear')
        for cn in self.classes:
            for data_type in 'nodes', 'journals':
                path = os.path.join(self.dir, '%s.%s' % (data_type, cn))
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
        """ grab a connection to the class db that will be used for
            multiple actions
        """
        return self.opendb('nodes.%s' % classname, mode)

    def determine_db_type(self, path):
        """ determine which DB wrote the class file
        """
        db_type = ''
        if os.path.exists(path):
            db_type = whichdb(path)
            if not db_type:
                raise hyperdb.DatabaseError(_("Couldn't identify database type"))
        elif os.path.exists(path+'.db'):
            # if the path ends in '.db', it's a dbm database, whether
            # anydbm says it's dbhash or not!
            db_type = 'dbm'
        return db_type

    def opendb(self, name, mode):
        """Low-level database opener that gets around anydbm/dbm
           eccentricities.
        """
        # figure the class db type
        path = os.path.join(os.getcwd(), self.dir, name)
        db_type = self.determine_db_type(path)

        # new database? let anydbm pick the best dbm
        # in Python 3+ the "dbm" ("anydbm" to us) module already uses the
        # whichdb() function to do this
        if not db_type or hasattr(anydbm, 'whichdb'):
            if __debug__:
                logging.getLogger('roundup.hyperdb.backend').debug(
                    "opendb anydbm.open(%(path)r, 'c')",
                    {"path": path,})
            return anydbm.open(path, 'c')

        # in Python <3 it anydbm was a little dumb so manually open the
        # database with the correct module
        try:
            dbm = __import__(db_type)
        except ImportError:
            if db_type == 'gdbm':
                try:
                    dbm = __import__('dbm.gnu')
                except ImportError:
                    raise hyperdb.DatabaseError(_(
                        "Couldn't open database - the required module '%s' "
                        "(as dbm.gnu) is not available") % db_type)
            else:
                raise hyperdb.DatabaseError(_(
                    "Couldn't open database - the "
                    "required module '%s' is not available") % db_type)
        if __debug__:
            logging.getLogger('roundup.hyperdb.backend').debug(
                "opendb %r.open(%r, %r)" % (db_type, path, mode))
        return dbm.open(path, mode)

    #
    # Node IDs
    #
    def newid(self, classname):
        """ Generate a new id for the given class
        """
        # open the ids DB - create if if doesn't exist
        db = self.opendb('_ids', 'c')
        if classname in db:
            newid = db[classname] = str(int(db[classname]) + 1)
        else:
            # the count() bit is transitional - older dbs won't start at 1
            newid = str(self.getclass(classname).count()+1)
            db[classname] = newid
        db.close()
        return newid

    def setid(self, classname, setid):
        """ Set the id counter: used during import of database
        """
        # open the ids DB - create if if doesn't exist
        db = self.opendb('_ids', 'c')
        db[classname] = str(setid)
        db.close()

    #
    # Nodes
    #
    def addnode(self, classname, nodeid, node):
        """ add the specified node to its class's db
        """
        # we'll be supplied these props if we're doing an import
        if 'creator' not in node:
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
        """ change the specified node
        """
        self.dirtynodes.setdefault(classname, {})[nodeid] = 1

        # can't set without having already loaded the node
        self.cache[classname][nodeid] = node
        self.savenode(classname, nodeid, node)

    def savenode(self, classname, nodeid, node):
        """ perform the saving of data specified by the set/addnode
        """
        if __debug__:
            logging.getLogger('roundup.hyperdb.backend').debug(
                'save %s%s %r' % (classname, nodeid, node))
        self.transactions.append((self.doSaveNode, (classname, nodeid, node)))

    def getnode(self, classname, nodeid, db=None, cache=1, allow_abort=True):
        """ get a node from the database

            Note the "cache" parameter is not used, and exists purely for
            backward compatibility!

            'allow_abort' is used only in sql backends.
        """
        # try the cache
        cache_dict = self.cache.setdefault(classname, {})
        if nodeid in cache_dict:
            if __debug__:
                logging.getLogger('roundup.hyperdb.backend').debug(
                    'get %s%s cached' % (classname, nodeid))
                self.stats['cache_hits'] += 1
            return cache_dict[nodeid]

        if __debug__:
            self.stats['cache_misses'] += 1
            start_t = time.time()
            logging.getLogger('roundup.hyperdb.backend').debug(
                'get %s%s' % (classname, nodeid))

        # get from the database and save in the cache
        if db is None:
            db = self.getclassdb(classname)
        if nodeid not in db:
            db.close()
            raise IndexError("no such %s %s" % (classname, nodeid))

        # check the uncommitted, destroyed nodes
        if (classname in self.destroyednodes and
                nodeid in self.destroyednodes[classname]):
            db.close()
            raise IndexError("no such %s %s" % (classname, nodeid))

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
        """Remove a node from the database. Called exclusively by the
           destroy() method on Class.
        """
        logging.getLogger('roundup.hyperdb.backend').info(
            'destroy %s%s' % (classname, nodeid))

        # remove from cache and newnodes if it's there
        if (classname in self.cache and nodeid in self.cache[classname]):
            del self.cache[classname][nodeid]
        if (classname in self.newnodes and nodeid in self.newnodes[classname]):
            del self.newnodes[classname][nodeid]

        # see if there's any obvious commit actions that we should get rid of
        for entry in self.transactions[:]:
            if entry[1][:2] == (classname, nodeid):
                self.transactions.remove(entry)

        # add to the destroyednodes map
        self.destroyednodes.setdefault(classname, {})[nodeid] = 1

        # add the destroy commit action
        self.transactions.append((self.doDestroyNode, (classname, nodeid)))
        self.transactions.append((FileStorage.destroy, (self, classname, nodeid)))

    def serialise(self, classname, node):
        """Copy the node contents, converting non-marshallable data into
           marshallable data.
        """
        properties = self.getclass(classname).getprops()
        d = {}
        for k, v in node.items():
            if k == self.RETIRED_FLAG:
                d[k] = v
                continue

            # if the property doesn't exist then we really don't care
            if k not in properties:
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
        """Decode the marshalled node data
        """
        properties = self.getclass(classname).getprops()
        d = {}
        for k, v in node.items():
            # if the property doesn't exist, or is the "retired" flag then
            # it won't be in the properties dict
            if k not in properties:
                d[k] = v
                continue

            # get the property spec
            prop = properties[k]

            if isinstance(prop, hyperdb.Date) and v is not None:
                d[k] = date.Date(v)
            elif isinstance(prop, hyperdb.Interval) and v is not None:
                d[k] = date.Interval(v)
            elif isinstance(prop, hyperdb.Password) and v is not None:
                d[k] = password.Password(encrypted=v, config=self.config)
            else:
                d[k] = v
        return d

    def hasnode(self, classname, nodeid, db=None):
        """ determine if the database has a given node
        """
        # try the cache
        cache = self.cache.setdefault(classname, {})
        if nodeid in cache:
            return 1

        # not in the cache - check the database
        if db is None:
            db = self.getclassdb(classname)
        return nodeid in db

    def countnodes(self, classname, db=None):
        count = 0

        # include the uncommitted nodes
        if classname in self.newnodes:
            count += len(self.newnodes[classname])
        if classname in self.destroyednodes:
            count -= len(self.destroyednodes[classname])

        # and count those in the DB
        if db is None:
            db = self.getclassdb(classname)
        return count + len(db)

    #
    # Files - special node properties
    # inherited from FileStorage

    #
    # Journal
    #
    def addjournal(self, classname, nodeid, action, params, creator=None,
                   creation=None):
        """ Journal the Action
        'action' may be:

            'set' -- 'params' is a dictionary of property values
            'create' -- 'params' is an empty dictionary as of
                      Wed Nov 06 11:38:43 2002 +0000
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retired' or 'restored' -- 'params' is None

            'creator' -- the user performing the action, which defaults to
            the current user.
        """
        if __debug__:
            logging.getLogger('roundup.hyperdb.backend').debug(
                'addjournal %s%s %s %r %s %r' % (
                    classname, nodeid, action, params, creator, creation))
        if creator is None:
            creator = self.getuid()
        self.transactions.append((self.doSaveJournal, (
            classname, nodeid, action, params, creator, creation)))

    def setjournal(self, classname, nodeid, journal):
        """Set the journal to the "journal" list."""
        if __debug__:
            logging.getLogger('roundup.hyperdb.backend').debug(
                'setjournal %s%s %r' % (classname, nodeid, journal))
        self.transactions.append((self.doSetJournal, (classname, nodeid,
                                                      journal)))

    def fix_journal(self, classname, journal):
        """ fix password entries to correct type """
        pwprops = {}
        for pn, prop in self.getclass(classname).properties.items():
            if isinstance(prop, hyperdb.Password):
                pwprops[pn] = 1
        if not pwprops:
            return journal
        for j in journal:
            if j[3] == 'set':
                for k in j[4].keys():
                    if k in pwprops and j[4][k]:
                        j[4][k] = password.JournalPassword(j[4][k])
        return journal

    def getjournal(self, classname, nodeid):
        """ get the journal for id

            Raise IndexError if the node doesn't exist (as per history()'s
            API)
        """
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
            db = self.opendb('journals.%s' % classname, 'r')
        except anydbm.error as error:
            if str(error) == "need 'c' or 'n' flag to open new db":
                raise IndexError('no such %s %s' % (classname, nodeid))
            elif error.args[0] != 2:
                # this isn't a "not found" error, be alarmed!
                raise
            if res:
                # we have unsaved journal entries, return them
                return self.fix_journal(classname, res)
            raise IndexError('no such %s %s' % (classname, nodeid))
        try:
            journal = marshal.loads(db[nodeid])
        except KeyError:
            db.close()
            if res:
                # we have some unsaved journal entries, be happy!
                return self.fix_journal(classname, res)
            raise IndexError('no such %s %s' % (classname, nodeid))
        db.close()

        # add all the saved journal entries for this node
        for nodeid, date_stamp, user, action, params in journal:
            res.append((nodeid, date.Date(date_stamp), user, action, params))
        return self.fix_journal(classname, res)

    def pack(self, pack_before):
        """ Delete all journal entries except "create" before 'pack_before'.
        """
        pack_before = pack_before.serialise()
        for classname in self.getclasses():
            packed = 0
            # get the journal db
            db_name = 'journals.%s' % classname
            path = os.path.join(os.getcwd(), self.dir, classname)
            db_type = self.determine_db_type(path)
            db = self.opendb(db_name, 'w')

            for key in map(b2s, db.keys()):
                # get the journal for this db entry
                journal = marshal.loads(db[key])
                kept_entries = []
                for entry in journal:
                    # unpack the entry
                    (nodeid, date_stamp, self.journaltag, action,
                        params) = entry
                    # if the entry is after the pack date, _or_ the initial
                    # create entry, then it stays
                    if date_stamp > pack_before or action == 'create':
                        kept_entries.append(entry)
                    else:
                        packed += 1
                db[key] = marshal.dumps(kept_entries)

                logging.getLogger('roundup.hyperdb.backend').info(
                    'packed %d %s items' % (packed, classname))

            if db_type == 'gdbm':
                db.reorganize()
            db.close()

    #
    # Basic transaction support
    #
    def commit(self):
        """ Commit the current transactions.

        Save all data changed since the database was opened or since the
        last commit() or rollback().
        """
        logging.getLogger('roundup.hyperdb.backend').info(
            'commit %s transactions' % (len(self.transactions)))

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

        # clear the transactions list now so the blobfile implementation
        # doesn't think there's still pending file commits when it tries
        # to access the file data
        self.transactions = []

        # reindex the nodes that request it
        for classname, nodeid in [k for k in reindex if k]:
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
        # upcall is necessary!
        roundupdb.Database.clearCache(self)

    def getCachedClassDB(self, classname):
        """ get the class db, looking in our cache of databases for commit
        """
        # get the database handle
        db_name = 'nodes.%s' % classname
        if db_name not in self.databases:
            self.databases[db_name] = self.getclassdb(classname, 'c')
        return self.databases[db_name]

    def doSaveNode(self, classname, nodeid, node):
        db = self.getCachedClassDB(classname)

        # now save the marshalled data
        db[nodeid] = marshal.dumps(self.serialise(classname, node))

        # return the classname, nodeid so we reindex this content
        return (classname, nodeid)

    def getCachedJournalDB(self, classname):
        """ get the journal db, looking in our cache of databases for commit
        """
        # get the database handle
        db_name = 'journals.%s' % classname
        if db_name not in self.databases:
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
        if nodeid in db:
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
        if nodeid in db:
            del db[nodeid]

        # delete from the database
        db = self.getCachedJournalDB(classname)
        if nodeid in db:
            del db[nodeid]

    def rollback(self):
        """ Reverse all actions from the current transaction.
        """
        logging.getLogger('roundup.hyperdb.backend').info(
            'rollback %s transactions' % (len(self.transactions)))

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
        """ Nothing to do
        """
        if self.lockfile is not None:
            locking.release_lock(self.lockfile)
            self.lockfile.close()
            self.lockfile = None


class Class(hyperdb.Class):
    """The handle to a particular class of nodes in a hyperdatabase."""

    def enableJournalling(self):
        """Turn journalling on for this class
        """
        self.do_journal = 1

    def disableJournalling(self):
        """Turn journalling off for this class
        """
        self.do_journal = 0

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

        These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError(_('Database open read-only'))
        self.fireAuditors('create', None, propvalues)
        newid = self.create_inner(**propvalues)
        self.fireReactors('create', newid, None)
        return newid

    def create_inner(self, **propvalues):
        """ Called by create, in-between the audit and react calls.
        """
        if 'id' in propvalues:
            raise KeyError('"id" is reserved')

        if self.db.journaltag is None:
            raise hyperdb.DatabaseError(_('Database open read-only'))

        if ('creator' in propvalues or 'actor' in propvalues or
                'creation' in propvalues or 'activity' in propvalues):
            raise KeyError('"creator", "actor", "creation" and '
                           '"activity" are reserved')

        for p in propvalues:
            prop = self.properties[p]
            if prop.computed:
                raise KeyError('"%s" is a computed property' % p)

        # new node's id
        newid = self.db.newid(self.classname)

        # validate propvalues
        num_re = re.compile(r'^\d+$')
        for key, value in propvalues.items():
            if key == self.key:
                try:
                    self.lookup(value)
                except KeyError:
                    pass
                else:
                    raise ValueError('node with key "%s" exists' % value)

            # try to handle this property
            try:
                prop = self.properties[key]
            except KeyError:
                raise KeyError('"%s" has no property "%s"' % (
                    self.classname, key))

            if value is not None and isinstance(prop, hyperdb.Link):
                if not isinstance(value, str):
                    raise ValueError('link value must be String')
                link_class = self.properties[key].classname
                # if it isn't a number, it's a key
                if not num_re.match(value):
                    try:
                        value = self.db.classes[link_class].lookup(value)
                    except (TypeError, KeyError):
                        raise IndexError('new property "%s": %s not a %s' % (
                            key, value, link_class))
                elif not self.db.getclass(link_class).hasnode(value):
                    raise IndexError('%s has no node %s' % (link_class, value))

                # save off the value
                propvalues[key] = value

                # register the link with the newly linked node
                if self.do_journal and self.properties[key].do_journal:
                    self.db.addjournal(link_class, value, 'link',
                                       (self.classname, newid, key))

            elif isinstance(prop, hyperdb.Multilink):
                if value is None:
                    value = []
                if not hasattr(value, '__iter__') or isinstance(value, str):
                    raise TypeError(
                        'new property "%s" not an iterable of ids' % key)

                # clean up and validate the list of links
                link_class = self.properties[key].classname
                l = []
                for entry in value:
                    if not isinstance(entry, str):
                        raise ValueError('"%s" multilink value (%r) '
                                         'must contain Strings' % (key, value))
                    # if it isn't a number, it's a key
                    if not num_re.match(entry):
                        try:
                            entry = self.db.classes[link_class].lookup(entry)
                        except (TypeError, KeyError):
                            raise IndexError(
                                'new property "%s": %s not a %s' % (
                                    key, entry,
                                    self.properties[key].classname))
                    l.append(entry)
                value = l
                propvalues[key] = value

                # handle additions
                for nodeid in value:
                    if not self.db.getclass(link_class).hasnode(nodeid):
                        raise IndexError('%s has no node %s' % (
                            link_class, nodeid))
                    # register the link with the newly linked node
                    if self.do_journal and self.properties[key].do_journal:
                        self.db.addjournal(link_class, nodeid, 'link',
                                           (self.classname, newid, key))

            elif isinstance(prop, hyperdb.String):
                if not isinstance(value, (str, unicode)):
                    raise TypeError('new property "%s" not a string' % key)
                if prop.indexme:
                    self.db.indexer.add_text(
                        (self.classname, newid, key), value)

            elif isinstance(prop, hyperdb.Password):
                if not isinstance(value, password.Password):
                    raise TypeError('new property "%s" not a Password' % key)

            elif isinstance(prop, hyperdb.Date):
                if value is not None and not isinstance(value, date.Date):
                    raise TypeError('new property "%s" not a Date' % key)

            elif isinstance(prop, hyperdb.Interval):
                if value is not None and not isinstance(value, date.Interval):
                    raise TypeError('new property "%s" not an Interval' % key)

            elif value is not None and isinstance(prop, hyperdb.Number):
                try:
                    float(value)
                except ValueError:
                    raise TypeError('new property "%s" not numeric' % key)

            elif value is not None and isinstance(prop, hyperdb.Integer):
                try:
                    int(value)
                except ValueError:
                    raise TypeError('new property "%s" not an integer' % key)

            elif value is not None and isinstance(prop, hyperdb.Boolean):
                try:
                    int(value)
                except ValueError:
                    raise TypeError('new property "%s" not boolean' % key)

        # make sure there's data where there needs to be
        for key, prop in self.properties.items():
            if key in propvalues:
                continue
            if key == self.key:
                raise ValueError('key property "%s" is required' % key)
            if isinstance(prop, hyperdb.Multilink):
                propvalues[key] = []

        # done
        self.db.addnode(self.classname, newid, propvalues)
        if self.do_journal:
            self.db.addjournal(self.classname, newid, 'create', {})

        return newid

    def get(self, nodeid, propname, default=_marker, cache=1, allow_abort=True):
        """Get the value of a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.  'propname' must be the name of a property
        of this class or a KeyError is raised.

        'cache' exists for backward compatibility, and is not used.

        'allow_abort' is used only in sql backends.

        Attempts to get the "creation" or "activity" properties should
        do the right thing.
        """
        if propname == 'id':
            return nodeid

        # get the node's dict
        d = self.db.getnode(self.classname, nodeid)

        # check for one of the special props
        if propname == 'creation':
            if 'creation' in d:
                return d['creation']
            if not self.do_journal:
                raise ValueError('Journalling is disabled for this class')
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                return journal[0][1]
            else:
                # on the strange chance that there's no journal
                return date.Date()
        if propname == 'activity':
            if 'activity' in d:
                return d['activity']
            if not self.do_journal:
                raise ValueError('Journalling is disabled for this class')
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                return self.db.getjournal(self.classname, nodeid)[-1][1]
            else:
                # on the strange chance that there's no journal
                return date.Date()
        if propname == 'creator':
            if 'creator' in d:
                return d['creator']
            if not self.do_journal:
                raise ValueError('Journalling is disabled for this class')
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                num_re = re.compile(r'^\d+$')
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
            if 'actor' in d:
                return d['actor']
            if not self.do_journal:
                raise ValueError('Journalling is disabled for this class')
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                num_re = re.compile(r'^\d+$')
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

        if isinstance(prop, hyperdb.Multilink) and prop.computed:
            cls = self.db.getclass(prop.rev_classname)
            ids = cls.find(**{prop.rev_propname: nodeid})
            return ids

        if propname not in d:
            if default is _marker:
                if isinstance(prop, hyperdb.Multilink):
                    return []
                else:
                    return None
            else:
                return default

        # return a dupe of the list so code doesn't get confused
        if isinstance(prop, hyperdb.Multilink):
            ids = d[propname][:]
            ids.sort(key=lambda x: int(x))
            return ids

        return d[propname]

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

        These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError(_('Database open read-only'))

        self.fireAuditors('set', nodeid, propvalues)
        oldvalues = copy.deepcopy(self.db.getnode(self.classname, nodeid))
        for name, prop in self.getprops(protected=0).items():
            if name in oldvalues:
                continue
            if isinstance(prop, hyperdb.Multilink):
                oldvalues[name] = []
            else:
                oldvalues[name] = None
        propvalues = self.set_inner(nodeid, **propvalues)
        self.fireReactors('set', nodeid, oldvalues)
        return propvalues

    def set_inner(self, nodeid, **propvalues):
        """ Called by set, in-between the audit and react calls.
        """
        if not propvalues:
            return propvalues

        if ('creator' in propvalues or 'actor' in propvalues or
                'creation' in propvalues or 'activity' in propvalues):
            raise KeyError('"creator", "actor", "creation" and '
                           '"activity" are reserved')

        if 'id' in propvalues:
            raise KeyError('"id" is reserved')

        for p in propvalues:
            prop = self.properties[p]
            if prop.computed:
                raise KeyError('"%s" is a computed property' % p)

        if self.db.journaltag is None:
            raise hyperdb.DatabaseError(_('Database open read-only'))

        node = self.db.getnode(self.classname, nodeid)
        if self.db.RETIRED_FLAG in node:
            raise IndexError
        num_re = re.compile(r'^\d+$')

        # if the journal value is to be different, store it in here
        journalvalues = {}

        # omit quiet properties from history/changelog
        quiet_props = []

        # list() propvalues 'cos it might be modified by the loop
        for propname, value in list(propvalues.items()):
            # check to make sure we're not duplicating an existing key
            if propname == self.key and node[propname] != value:
                try:
                    self.lookup(value)
                except KeyError:
                    pass
                else:
                    raise ValueError('node with key "%s" exists' % value)

            # this will raise the KeyError if the property isn't valid
            # ... we don't use getprops() here because we only care about
            # the writeable properties.
            try:
                prop = self.properties[propname]
            except KeyError:
                raise KeyError('"%s" has no property named "%s"' % (
                    self.classname, propname))

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
                    raise ValueError('property "%s" link value be a string' % (
                        propname))
                if isinstance(value, type('')) and not num_re.match(value):
                    try:
                        value = self.db.classes[link_class].lookup(value)
                    except (TypeError, KeyError):
                        raise IndexError('new property "%s": %s not a %s' % (
                            propname, value, prop.classname))

                if (value is not None and
                        not self.db.getclass(link_class).hasnode(value)):
                    raise IndexError('%s has no node %s' % (link_class,
                                                            value))

                if self.do_journal and prop.do_journal:
                    # register the unlink with the old linked node
                    if propname in node and node[propname] is not None:
                        self.db.addjournal(link_class, node[propname],
                                           'unlink',
                                           (self.classname, nodeid, propname))

                    # register the link with the newly linked node
                    if value is not None:
                        self.db.addjournal(link_class, value, 'link',
                                           (self.classname, nodeid, propname))

            elif isinstance(prop, hyperdb.Multilink):
                if value is None:
                    value = []
                if not hasattr(value, '__iter__') or isinstance(value, str):
                    raise TypeError('new property "%s" not an iterable of'
                                    ' ids' % propname)
                link_class = self.properties[propname].classname
                l = []
                for entry in value:
                    # if it isn't a number, it's a key
                    if not isinstance(entry, str):
                        raise ValueError('new property "%s" link value '
                                         'must be a string' % propname)
                    if not num_re.match(entry):
                        try:
                            entry = self.db.classes[link_class].lookup(entry)
                        except (TypeError, KeyError):
                            raise IndexError(
                                'new property "%s": %s not a %s' % (
                                    propname, entry,
                                    self.properties[propname].classname))
                    l.append(entry)
                value = l
                propvalues[propname] = value

                # figure the journal entry for this property
                add = []
                remove = []

                # handle removals
                if propname in node:
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
                        raise IndexError('%s has no node %s' % (
                            link_class, id))
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
                if value is not None and not isinstance(value, (str, unicode)):
                    raise TypeError('new property "%s" not a '
                                    'string' % propname)
                if prop.indexme:
                    self.db.indexer.add_text(
                        (self.classname, nodeid, propname),
                        value)

            elif isinstance(prop, hyperdb.Password):
                if not isinstance(value, password.Password):
                    raise TypeError('new property "%s" not a '
                                    'Password' % propname)
                propvalues[propname] = value
                journalvalues[propname] = \
                    current and password.JournalPassword(current)

            elif value is not None and isinstance(prop, hyperdb.Date):
                if not isinstance(value, date.Date):
                    raise TypeError('new property "%s" not a '
                                    'Date' % propname)
                propvalues[propname] = value

            elif value is not None and isinstance(prop, hyperdb.Interval):
                if not isinstance(value, date.Interval):
                    raise TypeError('new property "%s" not an '
                                    'Interval' % propname)
                propvalues[propname] = value

            elif value is not None and isinstance(prop, hyperdb.Number):
                try:
                    float(value)
                except ValueError:
                    raise TypeError('new property "%s" not '
                                    'numeric' % propname)

            elif value is not None and isinstance(prop, hyperdb.Integer):
                try:
                    int(value)
                except ValueError:
                    raise TypeError('new property "%s" not '
                                    'numeric' % propname)

            elif value is not None and isinstance(prop, hyperdb.Boolean):
                try:
                    int(value)
                except ValueError:
                    raise TypeError('new property "%s" not '
                                    'boolean' % propname)

            node[propname] = value

            # record quiet properties to omit from history/changelog
            if prop.quiet:
                quiet_props.append(propname)

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

        # remove quiet properties from output
        for propname in quiet_props:
            if propname in propvalues:
                del propvalues[propname]

        return propvalues

    def retire(self, nodeid):
        """Retire a node.

        The properties on the node remain available from the get() method,
        and the node's id is never reused.

        Retired nodes are not returned by the find(), list(), or lookup()
        methods, and other nodes may reuse the values of their key properties.

        These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError(_('Database open read-only'))

        self.fireAuditors('retire', nodeid, None)

        node = self.db.getnode(self.classname, nodeid)
        node[self.db.RETIRED_FLAG] = 1
        self.db.setnode(self.classname, nodeid, node)
        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, 'retired', None)

        self.fireReactors('retire', nodeid, None)

    def restore(self, nodeid):
        """Restore a retired node.

        Make node available for all operations like it was before retirement.
        """
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError(_('Database open read-only'))

        node = self.db.getnode(self.classname, nodeid)
        # check if key property was overrided
        key = self.getkey()
        try:
            # eval for exception side effect
            id = self.lookup(node[key])  # noqa: F841
        except KeyError:
            pass
        else:
            raise KeyError("Key property (%s) of retired node clashes "
                           "with existing one (%s)" % (key, node[key]))
        # Now we can safely restore node
        self.fireAuditors('restore', nodeid, None)
        del node[self.db.RETIRED_FLAG]
        self.db.setnode(self.classname, nodeid, node)
        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, 'restored', None)

        self.fireReactors('restore', nodeid, None)

    def is_retired(self, nodeid, cldb=None, allow_abort=True):
        """Return true if the node is retired.
           'allow_abort' is used only in sql backends.
        """
        node = self.db.getnode(self.classname, nodeid, cldb)
        if self.db.RETIRED_FLAG in node:
            return 1
        return 0

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
        """
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError(_('Database open read-only'))
        self.db.destroynode(self.classname, nodeid)

    # Locating nodes:
    def hasnode(self, nodeid):
        """Determine if the given nodeid actually exists
        """
        return self.db.hasnode(self.classname, nodeid)

    def setkey(self, propname):
        """Select a String property of this class to be the key property.

        'propname' must be the name of a String property of this class or
        None, or a TypeError is raised.  The values of the key property on
        all existing nodes must be unique or a ValueError is raised. If the
        property doesn't exist, KeyError is raised.
        """
        prop = self.getprops()[propname]
        if not isinstance(prop, hyperdb.String):
            raise TypeError('key properties must be String')
        self.key = propname

    def getkey(self):
        """Return the name of the key property for this class or None."""
        return self.key

    # TODO: set up a separate index db file for this? profile?
    def lookup(self, keyvalue):
        """Locate a particular node by its key property and return its id.

        If this class has no key property, a TypeError is raised.  If the
        'keyvalue' matches one of the values for the key property among
        the nodes in this class, the matching node's id is returned;
        otherwise a KeyError is raised.
        """
        if not self.key:
            raise TypeError('No key property set for '
                            'class %s' % self.classname)

        # special notation for looking up the current database user
        if keyvalue == '@current_user' and self.classname == 'user':
            keyvalue = self.db.user.get(self.db.getuid(), self.key)

        cldb = self.db.getclassdb(self.classname)
        try:
            for nodeid in self.getnodeids(cldb):
                node = self.db.getnode(self.classname, nodeid, cldb)
                if self.db.RETIRED_FLAG in node:
                    continue
                if self.key not in node:
                    continue
                if node[self.key] == keyvalue:
                    return nodeid
        finally:
            cldb.close()
        raise KeyError('No key (%s) value "%s" for "%s"' % (
            self.key, keyvalue, self.classname))

    # change from spec - allows multiple props to match
    def find(self, **propspec):
        """Get the ids of nodes in this class which link to the given nodes.

        'propspec' consists of keyword args propname=nodeid or
                   propname={nodeid:1, }
        'propname' must be the name of a property in this class, or a
                   KeyError is raised.  That property must be a Link or
                   Multilink property, or a TypeError is raised.

        Any node in this class whose 'propname' property links to any of
        the nodeids will be returned. Examples::

            db.issue.find(messages='1')
            db.issue.find(messages={'1':1,'3':1}, files={'7':1})
            db.issue.find(messages=('1','3'), files=('7',))
            db.issue.find(messages=['1','3'], files=['7'])
        """
        # shortcut
        if not propspec:
            return []

        # validate the args
        props = self.getprops()
        for propname, itemids in propspec.items():
            # check the prop is OK
            prop = props[propname]
            if not isinstance(prop, hyperdb.Link) and not isinstance(prop, hyperdb.Multilink):
                raise TypeError("'%s' not a Link/Multilink "
                                "property" % propname)

        # ok, now do the find
        cldb = self.db.getclassdb(self.classname)
        l = []
        rev_multilinks = []
        try:
            for id in self.getnodeids(db=cldb):
                item = self.db.getnode(self.classname, id, db=cldb)
                if self.db.RETIRED_FLAG in item:
                    continue
                for propname, itemids in propspec.items():
                    if not isinstance(itemids, dict):
                        if itemids is None or isinstance(itemids, type("")):
                            itemids = {itemids: 1}
                        else:
                            itemids = dict.fromkeys(itemids)

                    # special case if the item doesn't have this property
                    if propname not in item:
                        if None in itemids:
                            l.append(id)
                            break
                        continue

                    # grab the property definition and its value on this item
                    prop = props[propname]
                    value = item[propname]
                    if isinstance(prop, hyperdb.Link) and value in itemids:
                        l.append(id)
                        break
                    elif isinstance(prop, hyperdb.Multilink):
                        if prop.rev_property:
                            rev_multilinks.append((prop, itemids))
                            continue
                        hit = 0
                        for v in value:
                            if v in itemids:
                                l.append(id)
                                hit = 1
                                break
                        if hit:
                            break
            for prop, itemids in rev_multilinks:
                rprop = prop.rev_property
                fun = l.append
                if isinstance(rprop, hyperdb.Multilink):
                    fun = l.extend
                for id in itemids:
                    fun(rprop.cls.get(id, rprop.name))
            if rev_multilinks:
                l = list(sorted(set(l)))
        finally:
            cldb.close()
        return l

    def stringFind(self, **requirements):
        """Locate a particular node by matching a set of its String
        properties in a caseless search.

        If the property is not a String property, a TypeError is raised.

        The return is a list of the id of all nodes that match.
        """
        for propname in requirements:
            prop = self.properties[propname]
            if not isinstance(prop, hyperdb.String):
                raise TypeError("'%s' not a String property" % propname)
            requirements[propname] = requirements[propname].lower()
        l = []
        cldb = self.db.getclassdb(self.classname)
        try:
            for nodeid in self.getnodeids(cldb):
                node = self.db.getnode(self.classname, nodeid, cldb)
                if self.db.RETIRED_FLAG in node:
                    continue
                for key, value in requirements.items():
                    if key not in node:
                        break
                    if node[key] is None or node[key].lower() != value:
                        break
                else:
                    l.append(nodeid)
        finally:
            cldb.close()
        return l

    def list(self):
        """ Return a list of the ids of the active nodes in this class.
        """
        l = []
        cn = self.classname
        cldb = self.db.getclassdb(cn)
        try:
            for nodeid in self.getnodeids(cldb):
                node = self.db.getnode(cn, nodeid, cldb)
                if self.db.RETIRED_FLAG in node:
                    continue
                l.append(nodeid)
        finally:
            cldb.close()
        l.sort()
        return l

    def getnodeids(self, db=None, retired=None):
        """ Return a list of ALL nodeids

            Set retired=None to get all nodes. Otherwise it'll get all the
            retired or non-retired nodes, depending on the flag.
        """
        res = []

        # start off with the new nodes
        if self.classname in self.db.newnodes:
            res.extend(self.db.newnodes[self.classname])

        must_close = False
        if db is None:
            db = self.db.getclassdb(self.classname)
            must_close = True
        try:
            res.extend(map(b2s, db.keys()))

            # remove the uncommitted, destroyed nodes
            if self.classname in self.db.destroyednodes:
                for nodeid in self.db.destroyednodes[self.classname]:
                    if nodeid in db:
                        res.remove(nodeid)

            # check retired flag
            if retired is False or retired is True:
                l = []
                for nodeid in res:
                    node = self.db.getnode(self.classname, nodeid, db)
                    is_ret = self.db.RETIRED_FLAG in node
                    if retired == is_ret:
                        l.append(nodeid)
                res = l
        finally:
            if must_close:
                db.close()

        res.sort()
        return res

    num_re = re.compile(r'^\d+$')

    def _filter(self, search_matches, filterspec, proptree,
                num_re=num_re, retired=False,
                exact_match_spec=_marker):
        """Return a list of the ids of the nodes in this class that
        match the 'filter' spec, sorted by the group spec and then the
        sort spec.

        "filterspec" is {propname: value(s)}
        same for "exact_match_spec". The latter specifies exact matching
        for String type while String types in "filterspec" are searched
        for as case insensitive substring match.

        "sort" and "group" are (dir, prop) where dir is '+', '-' or None
        and prop is a prop name or None

        "search_matches" is a sequence type or None

        "retired" specifies if we should find only non-retired nodes
        (default) or only retired node (value True) or all nodes.

        The filter must match all properties specificed. If the property
        value to match is a list:

        1. String properties must match all elements in the list, and
        2. Other properties must match any of the elements in the list.
        """
        if __debug__:
            start_t = time.time()

        if exact_match_spec is _marker:
            exact_match_spec = {}

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

        for exact, filtertype in enumerate((filterspec, exact_match_spec)):
            for k, v in filtertype.items():
                propclass = props[k]
                if isinstance(propclass, hyperdb.Link):
                    if not isinstance(v, list):
                        v = [v]
                    if propclass.classname == 'user' and '@current_user' in v:
                        cu = self.db.getuid()
                        v = [x if x != "@current_user" else cu for x in v]
                    l.append((LINK, k, v))
                elif isinstance(propclass, hyperdb.Multilink):
                    # If it's a reverse multilink, we've already
                    # computed the ids of our own class.
                    if propclass.rev_property:
                        l.append((OTHER, 'id', v))
                    else:
                        # the value -1 is a special "not set" sentinel
                        if v in ('-1', ['-1']):
                            v = []
                        elif not isinstance(v, list):
                            v = [v]
                        l.append((MULTILINK, k, v))
                elif isinstance(propclass, hyperdb.String) and k != 'id':
                    if not isinstance(v, list):
                        v = [v]
                    for x in v:
                        if exact:
                            l.append((STRING, k, x))
                        else:
                            # simple glob searching
                            x = re.sub(r'([\|\{\}\\\.\+\[\]\(\)])', r'\\\1', x)
                            x = x.replace('?', '.')
                            x = x.replace('*', '.*?')
                            l.append((STRING, k, re.compile(x, re.I)))
                elif isinstance(propclass, hyperdb.Date):
                    try:
                        ranges = []
                        for d in v.split(','):
                            if d == '-':
                                ranges.append(None)
                                continue
                            date_rng = propclass.range_from_raw(d, self.db)
                            ranges.append(date_rng)
                        l.append((DATE, k, ranges))
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
                    if isinstance(v, str):
                        v = v.split(',')
                    if not isinstance(v, list):
                        v = [v]
                    bv = []
                    for val in v:
                        if isinstance(val, str):
                            bv.append(propclass.from_raw(val))
                        else:
                            bv.append(val)
                    l.append((OTHER, k, bv))

                elif k == 'id':
                    if not isinstance(v, list):
                        v = v.split(',')
                    l.append((OTHER, k, [str(int(val)) for val in v]))

                elif isinstance(propclass, hyperdb.Number):
                    if not isinstance(v, list):
                        try:
                            v = v.split(',')
                        except AttributeError:
                            v = [v]
                    l.append((OTHER, k, [float(val) for val in v]))

                elif isinstance(propclass, hyperdb.Integer):
                    if not isinstance(v, list):
                        try:
                            v = v.split(',')
                        except AttributeError:
                            v = [v]
                    l.append((OTHER, k, [int(val) for val in v]))

        filterspec = l

        # now, find all the nodes that pass filtering
        matches = []
        cldb = self.db.getclassdb(cn)
        t = 0
        try:
            # TODO: only full-scan once (use items())
            for nodeid in self.getnodeids(cldb, retired=retired):
                node = self.db.getnode(cn, nodeid, cldb)
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
                        try:
                            expr = Expression(v, is_link=True)
                        except ExpressionError as e:
                            e.context['class'] = cn
                            e.context['attr'] = k
                            raise
                        if expr.evaluate(nv):
                            match = 1
                    elif t == MULTILINK:
                        # multilink - if any of the nodeids required by the
                        # filterspec aren't in this node's property, then skip
                        # it
                        nv = node.get(k, [])

                        # check for matching the absence of multilink values
                        if not v:
                            match = not nv
                        else:
                            # otherwise, make sure this node has each of the
                            # required values
                            try:
                                expr = Expression(v)
                            except ExpressionError as e:
                                e.context['class'] = cn
                                e.context['attr'] = k
                                raise
                            if expr.evaluate(nv):
                                match = 1
                    elif t == STRING:
                        if nv is None:
                            nv = ''
                        if is_us(v):
                            # Exact match
                            match = (nv == v)
                        else:
                            # RE search
                            match = v.search(nv)
                    elif t == DATE:
                        for x in v:
                            if x is None or nv is None:
                                if nv is None and x is None:
                                    match = 1
                                    break
                                continue
                            elif x.to_value:
                                if x.from_value <= nv <= x.to_value:
                                    match = 1
                                    break
                            else:
                                if x.from_value <= nv:
                                    match = 1
                                    break
                    elif t == INTERVAL:
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
                    if v[0] in search_matches:
                        k.append(v)
                matches = k

            # add sorting information to the proptree
            JPROPS = {'actor': 1, 'activity': 1, 'creator': 1, 'creation': 1}
            children = []
            if proptree:
                children = proptree.sortable_children()
            for pt in children:
                dir = pt.sort_direction
                prop = pt.name
                assert (dir and prop)
                propclass = props[prop]
                pt.sort_ids = []
                is_pointer = isinstance(propclass, (hyperdb.Link,
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
                            if prop in JPROPS:
                                # force lookup of the special journal prop
                                v = self.get(itemid, prop)
                            else:
                                # the node doesn't have a value for this
                                # property
                                v = None
                                if isinstance(propclass, hyperdb.Multilink):
                                    v = []
                                if prop == 'id':
                                    v = int(itemid)
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
                            if key != 'id':
                                if v not in lcache:
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
           those which may not be modified.

           In addition to the actual properties on the node, these
           methods provide the "creation" and "activity" properties. If the
           "protected" flag is true, we include protected properties - those
           which may not be modified.
        """
        d = self.properties.copy()
        if protected:
            d['id'] = hyperdb.String()
            d['creation'] = hyperdb.Date()
            d['activity'] = hyperdb.Date()
            d['creator'] = hyperdb.Link('user')
            d['actor'] = hyperdb.Link('user')
        return d

    def addprop(self, **properties):
        """Add properties to this class.

        The keyword arguments in 'properties' must map names to property
        objects, or a TypeError is raised.  None of the keys in 'properties'
        may collide with the names of existing properties, or a ValueError
        is raised before any properties have been added.
        """
        for key in properties:
            if key in self.properties:
                raise ValueError(key)
        self.properties.update(properties)

    def index(self, nodeid):
        """ Add (or refresh) the node to search indexes """
        # find all the String properties that have indexme
        for prop, propclass in self.getprops().items():
            if isinstance(propclass, hyperdb.String) and propclass.indexme:
                # index them under (classname, nodeid, property)
                self.db.indexer.add_text((self.classname, nodeid, prop),
                                         str(self.get(nodeid, prop)))

    #
    # import / export support
    #
    def export_list(self, propnames, nodeid):
        """ Export a node - generate a list of CSV-able data in the order
            specified by propnames for the given node.
        """
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
            l.append(repr_export(value))

        # append retired flag
        l.append(repr_export(self.is_retired(nodeid)))

        return l

    def import_list(self, propnames, proplist):
        """ Import a node - all information including "id" is present and
            should not be sanity checked. Triggers are not triggered. The
            journal should be initialised using the "creator" and "created"
            information.

            Return the nodeid of the node imported.
        """
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError(_('Database open read-only'))
        properties = self.getprops()

        # make the new node's property map
        d = {}
        newid = None
        for i in range(len(propnames)):
            # Figure the property for this column
            propname = propnames[i]

            # Use eval_import to reverse the repr_export() used to
            # output the CSV
            value = eval_import(proplist[i])

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
                value = password.Password(encrypted=value,
                                          config=self.db.config)
            d[propname] = value

        # get a new id if necessary
        if newid is None:
            newid = self.db.newid(self.classname)

        # add the node and journal
        self.db.addnode(self.classname, newid, d)
        return newid

    def export_journals(self):
        """Export a class's journal - generate a list of lists of
        CSV-able data:

            nodeid, date, user, action, params

        No heading here - the columns are fixed.
        """
        properties = self.getprops()
        r = []
        for nodeid in self.getnodeids():
            for nodeid, date_, user, action, params in self.history(
                    nodeid, enforceperm=False, skipquiet=False):
                date_ = date_.get_tuple()
                if action == 'set':
                    export_data = {}
                    for propname, value in params.items():
                        if propname not in properties:
                            # property no longer in the schema
                            continue

                        prop = properties[propname]
                        # make sure the params are eval()'able
                        if value is None:
                            pass
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
                r.append([repr_export(nodeid), repr_export(date_),
                          repr_export(user), repr_export(action),
                          repr_export(params)])
        return r


class FileClass(hyperdb.FileClass, Class):
    # Use for explicit upcalls in generic code, for py2 compat we cannot
    # use super() without making everything a new-style class.
    subclass = Class
    def __init__(self, db, classname, **properties):
        self._update_properties(properties)
        Class.__init__(self, db, classname, **properties)

class IssueClass(Class, roundupdb.IssueClass):
    # Use for explicit upcalls in generic code, for py2 compat we cannot
    # use super() without making everything a new-style class.
    subclass = Class
    def __init__(self, db, classname, **properties):
        self._update_properties(classname, properties)
        Class.__init__(self, db, classname, **properties)

# vim: set et sts=4 sw=4 :
