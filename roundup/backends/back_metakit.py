# $Id: back_metakit.py,v 1.113 2006-08-29 04:20:50 richard Exp $
'''Metakit backend for Roundup, originally by Gordon McMillan.

Known Current Bugs:

- You can't change a class' key properly. This shouldn't be too hard to fix.
- Some unit tests are overridden.

Notes by Richard:

This backend has some behaviour specific to metakit:

- there's no concept of an explicit "unset" in metakit, so all types
  have some "unset" value:

  ========= ===== ======================================================
  Type      Value Action when fetching from mk
  ========= ===== ======================================================
  Strings   ''    convert to None
  Date      0     (seconds since 1970-01-01.00:00:00) convert to None
  Interval  ''    convert to None
  Number    0     ambiguious :( - do nothing (see BACKWARDS_COMPATIBLE)
  Boolean   0     ambiguious :( - do nothing (see BACKWARDS_COMPATABILE)
  Link      0     convert to None
  Multilink []    actually, mk can handle this one ;)
  Password  ''    convert to None
  ========= ===== ======================================================

  The get/set routines handle these values accordingly by converting
  to/from None where they can. The Number/Boolean types are not able
  to handle an "unset" at all, so they default the "unset" to 0.
- Metakit relies in reference counting to close the database, there is
  no explicit close call.  This can cause issues if a metakit
  database is referenced multiple times, one might not actually be
  closing the db.
- probably a bunch of stuff that I'm not aware of yet because I haven't
  fully read through the source. One of these days....
'''
__docformat__ = 'restructuredtext'
# Enable this flag to break backwards compatibility (i.e. can't read old
# databases) but comply with more roundup features, like adding NULL support.
BACKWARDS_COMPATIBLE = 1

from roundup import hyperdb, date, password, roundupdb, security
from roundup.support import reversed
import logging
import metakit
from sessions_dbm import Sessions, OneTimeKeys
import re, marshal, os, sys, time, calendar, shutil
from indexer_common import Indexer as CommonIndexer
import locking
from roundup.date import Range
from blobfiles import files_in_dir

# view modes for opening
# XXX FIXME BPK -> these don't do anything, they are ignored
#  should we just get rid of them for simplicities sake?
READ = 0
READWRITE = 1

def db_exists(config):
    return os.path.exists(os.path.join(config.TRACKER_HOME, 'db',
        'tracker.mk4'))

def db_nuke(config):
    shutil.rmtree(os.path.join(config.TRACKER_HOME, 'db'))

# general metakit error
class MKBackendError(Exception):
    pass

_dbs = {}

def Database(config, journaltag=None):
    ''' Only have a single instance of the Database class for each instance
    '''
    db = _dbs.get(config.DATABASE, None)
    if db is None or db._db is None:
        db = _Database(config, journaltag)
        _dbs[config.DATABASE] = db
    else:
        db.journaltag = journaltag
    return db

class _Database(hyperdb.Database, roundupdb.Database):
    # Metakit has no concept of an explicit NULL
    BACKEND_MISSING_STRING = ''
    BACKEND_MISSING_NUMBER = 0
    BACKEND_MISSING_BOOLEAN = 0

    def __init__(self, config, journaltag=None):
        self.config = config
        self.journaltag = journaltag
        self.classes = {}
        self.dirty = 0
        self.lockfile = None
        self._db = self.__open()
        self.indexer = Indexer(self)
        self.security = security.Security(self)

        self.stats = {'cache_hits': 0, 'cache_misses': 0, 'get_items': 0,
            'filtering': 0}

        os.umask(config.UMASK)

    def post_init(self):
        if self.indexer.should_reindex():
            self.reindex()

    def refresh_database(self):
        # XXX handle refresh
        self.reindex()

    def reindex(self, classname=None):
        if classname:
            classes = [self.getclass(classname)]
        else:
            classes = self.classes.values()
        for klass in classes:
            for nodeid in klass.list():
                klass.index(nodeid)
        self.indexer.save_index()

    def getSessionManager(self):
        return Sessions(self)

    def getOTKManager(self):
        return OneTimeKeys(self)

    # --- defined in ping's spec
    def __getattr__(self, classname):
        if classname == 'transactions':
            return self.dirty
        # fall back on the classes
        try:
            return self.getclass(classname)
        except KeyError, msg:
            # KeyError's not appropriate here
            raise AttributeError, str(msg)
    def getclass(self, classname):
        try:
            return self.classes[classname]
        except KeyError:
            raise KeyError, 'There is no class called "%s"'%classname
    def getclasses(self):
        return self.classes.keys()
    # --- end of ping's spec

    # --- exposed methods
    def commit(self, fail_ok=False):
        ''' Commit the current transactions.

        Save all data changed since the database was opened or since the
        last commit() or rollback().

        fail_ok indicates that the commit is allowed to fail. This is used
        in the web interface when committing cleaning of the session
        database. We don't care if there's a concurrency issue there.

        The only backend this seems to affect is postgres.
        '''
        if self.dirty:
            self._db.commit()
            for cl in self.classes.values():
                cl._commit()
            self.indexer.save_index()
        self.dirty = 0
    def rollback(self):
        '''roll back all changes since the last commit'''
        if self.dirty:
            for cl in self.classes.values():
                cl._rollback()
            self._db.rollback()
            self._db = None
            self._db = metakit.storage(self.dbnm, 1)
            self.hist = self._db.view('history')
            self.tables = self._db.view('tables')
            self.indexer.rollback()
            self.indexer.datadb = self._db
        self.dirty = 0
    def clearCache(self):
        '''clear the internal cache by committing all pending database changes'''
        for cl in self.classes.values():
            cl._commit()
    def clear(self):
        '''clear the internal cache but don't commit any changes'''
        for cl in self.classes.values():
            cl._clear()
    def hasnode(self, classname, nodeid):
        '''does a particular class contain a nodeid?'''
        return self.getclass(classname).hasnode(nodeid)
    def pack(self, pack_before):
        ''' Delete all journal entries except "create" before 'pack_before'.
        '''
        mindate = int(calendar.timegm(pack_before.get_tuple()))
        i = 0
        while i < len(self.hist):
            if self.hist[i].date < mindate and self.hist[i].action != _CREATE:
                self.hist.delete(i)
            else:
                i = i + 1
    def addclass(self, cl):
        ''' Add a Class to the hyperdatabase.
        '''
        cn = cl.classname
        self.classes[cn] = cl
        if self.tables.find(name=cn) < 0:
            self.tables.append(name=cn)

        # add default Edit and View permissions
        self.security.addPermission(name="Create", klass=cn,
            description="User is allowed to create "+cn)
        self.security.addPermission(name="Edit", klass=cn,
            description="User is allowed to edit "+cn)
        self.security.addPermission(name="View", klass=cn,
            description="User is allowed to access "+cn)

    def addjournal(self, tablenm, nodeid, action, params, creator=None,
                   creation=None):
        ''' Journal the Action
        'action' may be:

            'create' or 'set' -- 'params' is a dictionary of property values
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retire' -- 'params' is None
        '''
        tblid = self.tables.find(name=tablenm)
        if tblid == -1:
            tblid = self.tables.append(name=tablenm)
        if creator is None:
            creator = int(self.getuid())
        else:
            try:
                creator = int(creator)
            except TypeError:
                creator = int(self.getclass('user').lookup(creator))
        if creation is None:
            creation = int(time.time())
        elif isinstance(creation, date.Date):
            creation = int(calendar.timegm(creation.get_tuple()))
        # tableid:I,nodeid:I,date:I,user:I,action:I,params:B
        self.hist.append(tableid=tblid,
                         nodeid=int(nodeid),
                         date=creation,
                         action=action,
                         user=creator,
                         params=marshal.dumps(params))

    def setjournal(self, tablenm, nodeid, journal):
        '''Set the journal to the "journal" list.'''
        tblid = self.tables.find(name=tablenm)
        if tblid == -1:
            tblid = self.tables.append(name=tablenm)
        for nodeid, date, user, action, params in journal:
            # tableid:I,nodeid:I,date:I,user:I,action:I,params:B
            self.hist.append(tableid=tblid,
                             nodeid=int(nodeid),
                             date=date,
                             action=action,
                             user=int(user),
                             params=marshal.dumps(params))

    def getjournal(self, tablenm, nodeid):
        ''' get the journal for id
        '''
        rslt = []
        tblid = self.tables.find(name=tablenm)
        if tblid == -1:
            return rslt
        q = self.hist.select(tableid=tblid, nodeid=int(nodeid))
        if len(q) == 0:
            raise IndexError, "no history for id %s in %s" % (nodeid, tablenm)
        i = 0
        #userclass = self.getclass('user')
        for row in q:
            try:
                params = marshal.loads(row.params)
            except ValueError:
                logging.getLogger("hyperdb").error(
                    "history couldn't unmarshal %r" % row.params)
                params = {}
            #usernm = userclass.get(str(row.user), 'username')
            dt = date.Date(time.gmtime(row.date))
            #rslt.append((nodeid, dt, usernm, _actionnames[row.action], params))
            rslt.append((nodeid, dt, str(row.user), _actionnames[row.action],
                params))
        return rslt

    def destroyjournal(self, tablenm, nodeid):
        nodeid = int(nodeid)
        tblid = self.tables.find(name=tablenm)
        if tblid == -1:
            return
        i = 0
        hist = self.hist
        while i < len(hist):
            if hist[i].tableid == tblid and hist[i].nodeid == nodeid:
                hist.delete(i)
            else:
                i = i + 1
        self.dirty = 1

    def close(self):
        ''' Close off the connection.
        '''
        # de-reference count the metakit databases,
        #  as this is the only way they will be closed
        for cl in self.classes.values():
            cl.db = None
        self._db = None
        if self.lockfile is not None:
            locking.release_lock(self.lockfile)
        if _dbs.has_key(self.config.DATABASE):
            del _dbs[self.config.DATABASE]
        if self.lockfile is not None:
            self.lockfile.close()
            self.lockfile = None
        self.classes = {}

        # force the indexer to close
        self.indexer.close()
        self.indexer = None

    # --- internal
    def __open(self):
        ''' Open the metakit database
        '''
        # make the database dir if it doesn't exist
        if not os.path.exists(self.config.DATABASE):
            os.makedirs(self.config.DATABASE)

        # figure the file names
        self.dbnm = db = os.path.join(self.config.DATABASE, 'tracker.mk4')
        lockfilenm = db[:-3]+'lck'

        # get the database lock
        self.lockfile = locking.acquire_lock(lockfilenm)
        self.lockfile.write(str(os.getpid()))
        self.lockfile.flush()

        # see if the schema has changed since last db access
        self.fastopen = 0
        if os.path.exists(db):
            dbtm = os.path.getmtime(db)
            schemafile = os.path.join(self.config['HOME'], 'schema.py')
            if not os.path.isfile(schemafile):
                # try old-style schema
                schemafile = os.path.join(self.config['HOME'], 'dbinit.py')
            if os.path.isfile(schemafile) \
            and (os.path.getmtime(schemafile) < dbtm):
                # found schema file - it's older than the db
                self.fastopen = 1

        # open the db
        db = metakit.storage(db, 1)
        hist = db.view('history')
        tables = db.view('tables')
        if not self.fastopen:
            # create the database if it's brand new
            if not hist.structure():
                hist = db.getas('history[tableid:I,nodeid:I,date:I,user:I,action:I,params:B]')
            if not tables.structure():
                tables = db.getas('tables[name:S]')
            db.commit()

        # we now have an open, initialised database
        self.tables = tables
        self.hist = hist
        return db

    def setid(self, classname, maxid):
        ''' No-op in metakit
        '''
        cls = self.getclass(classname)
        cls.setid(int(maxid))

    def numfiles(self):
        '''Get number of files in storage, even across subdirectories.
        '''
        files_dir = os.path.join(self.config.DATABASE, 'files')
        return files_in_dir(files_dir)

_STRINGTYPE = type('')
_LISTTYPE = type([])
_CREATE, _SET, _RETIRE, _LINK, _UNLINK, _RESTORE = range(6)

_actionnames = {
    _CREATE : 'create',
    _SET : 'set',
    _RETIRE : 'retire',
    _RESTORE : 'restore',
    _LINK : 'link',
    _UNLINK : 'unlink',
}

_names_to_actionnames = {
    'create': _CREATE,
    'set': _SET,
    'retire': _RETIRE,
    'restore': _RESTORE,
    'link': _LINK,
    'unlink': _UNLINK,
}

_marker = []

_ALLOWSETTINGPRIVATEPROPS = 0

class Class(hyperdb.Class):
    ''' The handle to a particular class of nodes in a hyperdatabase.

        All methods except __repr__ and getnode must be implemented by a
        concrete backend Class of which this is one.
    '''

    privateprops = None
    def __init__(self, db, classname, **properties):
        if hasattr(db, classname):
            raise ValueError, "Class %s already exists"%classname

        hyperdb.Class.__init__ (self, db, classname, **properties)
        self.db = db # why isn't this a weakref as for other backends??
        self.key = None
        self.ruprops = self.properties
        self.privateprops = { 'id' : hyperdb.String(),
                              'activity' : hyperdb.Date(),
                              'actor' : hyperdb.Link('user'),
                              'creation' : hyperdb.Date(),
                              'creator'  : hyperdb.Link('user') }

        self.idcache = {}
        self.uncommitted = {}
        self.comactions = []
        self.rbactions = []

        view = self.__getview()
        self.maxid = 1
        if view:
            self.maxid = view[-1].id + 1

    def setid(self, maxid):
        self.maxid = maxid + 1

    def enableJournalling(self):
        '''Turn journalling on for this class
        '''
        self.do_journal = 1

    def disableJournalling(self):
        '''Turn journalling off for this class
        '''
        self.do_journal = 0

    # --- the hyperdb.Class methods
    def create(self, **propvalues):
        ''' Create a new node of this class and return its id.

        The keyword arguments in 'propvalues' map property names to values.

        The values of arguments must be acceptable for the types of their
        corresponding properties or a TypeError is raised.

        If this class has a key property, it must be present and its value
        must not collide with other key strings or a ValueError is raised.

        Any other properties on this class that are missing from the
        'propvalues' dictionary are set to None.

        If an id in a link or multilink property does not refer to a valid
        node, an IndexError is raised.
        '''
        if not propvalues:
            raise ValueError, "Need something to create!"
        self.fireAuditors('create', None, propvalues)
        newid = self.create_inner(**propvalues)
        self.fireReactors('create', newid, None)
        return newid

    def create_inner(self, **propvalues):
       ''' Called by create, in-between the audit and react calls.
       '''
       rowdict = {}
       rowdict['id'] = newid = self.maxid
       self.maxid += 1
       ndx = self.getview(READWRITE).append(rowdict)
       propvalues['#ISNEW'] = 1
       try:
           self.set_inner(str(newid), **propvalues)
       except Exception:
           self.maxid -= 1
           raise
       return str(newid)

    def get(self, nodeid, propname, default=_marker, cache=1):
        '''Get the value of a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.  'propname' must be the name of a property
        of this class or a KeyError is raised.

        'cache' exists for backwards compatibility, and is not used.
        '''
        view = self.getview()
        id = int(nodeid)
        if cache == 0:
            oldnode = self.uncommitted.get(id, None)
            if oldnode and oldnode.has_key(propname):
                raw = oldnode[propname]
                converter = _converters.get(raw.__class__, None)
                if converter:
                    return converter(raw)
                return raw
        ndx = self.idcache.get(id, None)

        if ndx is None:
            ndx = view.find(id=id)
            if ndx < 0:
                raise IndexError, "%s has no node %s" % (self.classname, nodeid)
            self.idcache[id] = ndx
        try:
            raw = getattr(view[ndx], propname)
        except AttributeError:
            raise KeyError, propname
        rutyp = self.ruprops.get(propname, None)

        if rutyp is None:
            rutyp = self.privateprops[propname]

        converter = _converters.get(rutyp.__class__, None)
        if converter:
            raw = converter(raw)
        return raw

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
        '''
        self.fireAuditors('set', nodeid, propvalues)
        propvalues, oldnode = self.set_inner(nodeid, **propvalues)
        self.fireReactors('set', nodeid, oldnode)

    def set_inner(self, nodeid, **propvalues):
        '''Called outside of auditors'''
        isnew = 0
        if propvalues.has_key('#ISNEW'):
            isnew = 1
            del propvalues['#ISNEW']

        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError, 'Database open read-only'
        view = self.getview(READWRITE)

        # node must exist & not be retired
        id = int(nodeid)
        ndx = view.find(id=id)
        if ndx < 0:
            raise IndexError, "%s has no node %s" % (self.classname, nodeid)
        row = view[ndx]
        if row._isdel:
            raise IndexError, "%s has no node %s" % (self.classname, nodeid)
        oldnode = self.uncommitted.setdefault(id, {})
        changes = {}

        for key, value in propvalues.items():
            # this will raise the KeyError if the property isn't valid
            # ... we don't use getprops() here because we only care about
            # the writeable properties.
            if _ALLOWSETTINGPRIVATEPROPS:
                prop = self.ruprops.get(key, None)
                if not prop:
                    prop = self.privateprops[key]
            else:
                prop = self.ruprops[key]
            converter = _converters.get(prop.__class__, lambda v: v)
            # if the value's the same as the existing value, no sense in
            # doing anything
            oldvalue = converter(getattr(row, key))
            if  value == oldvalue:
                del propvalues[key]
                continue

            # check to make sure we're not duplicating an existing key
            if key == self.key:
                iv = self.getindexview(READWRITE)
                ndx = iv.find(k=value)
                if ndx == -1:
                    iv.append(k=value, i=row.id)
                    if not isnew:
                        ndx = iv.find(k=oldvalue)
                        if ndx > -1:
                            iv.delete(ndx)
                else:
                    raise ValueError, 'node with key "%s" exists'%value

            # do stuff based on the prop type
            if isinstance(prop, hyperdb.Link):
                link_class = prop.classname
                # must be a string or None
                if value is not None and not isinstance(value, type('')):
                    raise ValueError, 'property "%s" link value be a string'%(
                        key)
                # Roundup sets to "unselected" by passing None
                if value is None:
                    value = 0
                # if it isn't a number, it's a key
                try:
                    int(value)
                except ValueError:
                    try:
                        value = self.db.getclass(link_class).lookup(value)
                    except (TypeError, KeyError):
                        raise IndexError, 'new property "%s": %s not a %s'%(
                            key, value, prop.classname)

                if (value is not None and
                        not self.db.getclass(link_class).hasnode(value)):
                    raise IndexError, '%s has no node %s'%(link_class, value)

                setattr(row, key, int(value))
                changes[key] = oldvalue

                if self.do_journal and prop.do_journal:
                    # register the unlink with the old linked node
                    if oldvalue:
                        self.db.addjournal(link_class, oldvalue, _UNLINK,
                            (self.classname, str(row.id), key))

                    # register the link with the newly linked node
                    if value:
                        self.db.addjournal(link_class, value, _LINK,
                            (self.classname, str(row.id), key))

            elif isinstance(prop, hyperdb.Multilink):
                if value is not None and type(value) != _LISTTYPE:
                    raise TypeError, 'new property "%s" not a list of ids'%key
                link_class = prop.classname
                l = []
                if value is None:
                    value = []
                for entry in value:
                    if type(entry) != _STRINGTYPE:
                        raise ValueError, 'new property "%s" link value ' \
                            'must be a string'%key
                    # if it isn't a number, it's a key
                    try:
                        int(entry)
                    except ValueError:
                        try:
                            entry = self.db.getclass(link_class).lookup(entry)
                        except (TypeError, KeyError):
                            raise IndexError, 'new property "%s": %s not a %s'%(
                                key, entry, prop.classname)
                    l.append(entry)
                propvalues[key] = value = l

                # handle removals
                rmvd = []
                for id in oldvalue:
                    if id not in value:
                        rmvd.append(id)
                        # register the unlink with the old linked node
                        if self.do_journal and prop.do_journal:
                            self.db.addjournal(link_class, id, _UNLINK,
                                (self.classname, str(row.id), key))

                # handle additions
                adds = []
                for id in value:
                    if id not in oldvalue:
                        if not self.db.getclass(link_class).hasnode(id):
                            raise IndexError, '%s has no node %s'%(
                                link_class, id)
                        adds.append(id)
                        # register the link with the newly linked node
                        if self.do_journal and prop.do_journal:
                            self.db.addjournal(link_class, id, _LINK,
                                (self.classname, str(row.id), key))

                # perform the modifications on the actual property value
                sv = getattr(row, key)
                i = 0
                while i < len(sv):
                    if str(sv[i].fid) in rmvd:
                        sv.delete(i)
                    else:
                        i += 1
                for id in adds:
                    sv.append(fid=int(id))

                # figure the journal entry
                l = []
                if adds:
                    l.append(('+', adds))
                if rmvd:
                    l.append(('-', rmvd))
                if l:
                    changes[key] = tuple(l)
                #changes[key] = oldvalue

                if not rmvd and not adds:
                    del propvalues[key]

            elif isinstance(prop, hyperdb.String):
                if value is not None and type(value) != _STRINGTYPE:
                    raise TypeError, 'new property "%s" not a string'%key
                if value is None:
                    value = ''
                setattr(row, key, value)
                changes[key] = oldvalue
                if hasattr(prop, 'isfilename') and prop.isfilename:
                    propvalues[key] = os.path.basename(value)
                if prop.indexme:
                    self.db.indexer.add_text((self.classname, nodeid, key),
                        value, 'text/plain')

            elif isinstance(prop, hyperdb.Password):
                if value is not None and not isinstance(value, password.Password):
                    raise TypeError, 'new property "%s" not a Password'% key
                if value is None:
                    value = ''
                setattr(row, key, str(value))
                changes[key] = str(oldvalue)
                propvalues[key] = str(value)

            elif isinstance(prop, hyperdb.Date):
                if value is not None and not isinstance(value, date.Date):
                    raise TypeError, 'new property "%s" not a Date'% key
                if value is None:
                    setattr(row, key, 0)
                else:
                    setattr(row, key, int(calendar.timegm(value.get_tuple())))
                if oldvalue is None:
                    changes[key] = oldvalue
                else:
                    changes[key] = str(oldvalue)
                propvalues[key] = str(value)

            elif isinstance(prop, hyperdb.Interval):
                if value is not None and not isinstance(value, date.Interval):
                    raise TypeError, 'new property "%s" not an Interval'% key
                if value is None:
                    setattr(row, key, '')
                else:
                    # kedder: we should store interval values serialized
                    setattr(row, key, value.serialise())
                changes[key] = str(oldvalue)
                propvalues[key] = str(value)

            elif isinstance(prop, hyperdb.Number):
                if value is None:
                    v = 0
                else:
                    try:
                        v = float(value)
                    except ValueError:
                        raise TypeError, "%s (%s) is not numeric"%(key, repr(value))
                    if not BACKWARDS_COMPATIBLE:
                        if v >=0:
                            v = v + 1
                setattr(row, key, v)
                changes[key] = oldvalue
                propvalues[key] = value

            elif isinstance(prop, hyperdb.Boolean):
                if value is None:
                    bv = 0
                elif value not in (0,1):
                    raise TypeError, "%s (%s) is not boolean"%(key, repr(value))
                else:
                    bv = value
                    if not BACKWARDS_COMPATIBLE:
                        bv += 1
                setattr(row, key, bv)
                changes[key] = oldvalue
                propvalues[key] = value

            oldnode[key] = oldvalue

        # nothing to do?
        if not isnew and not propvalues:
            return propvalues, oldnode
        if not propvalues.has_key('activity'):
            row.activity = int(time.time())
        if not propvalues.has_key('actor'):
            row.actor = int(self.db.getuid())
        if isnew:
            if not row.creation:
                row.creation = int(time.time())
            if not row.creator:
                row.creator = int(self.db.getuid())

        self.db.dirty = 1

        if self.do_journal:
            if isnew:
                self.db.addjournal(self.classname, nodeid, _CREATE, {})
            else:
                self.db.addjournal(self.classname, nodeid, _SET, changes)

        return propvalues, oldnode

    def retire(self, nodeid):
        '''Retire a node.

        The properties on the node remain available from the get() method,
        and the node's id is never reused.

        Retired nodes are not returned by the find(), list(), or lookup()
        methods, and other nodes may reuse the values of their key properties.
        '''
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError, 'Database open read-only'
        self.fireAuditors('retire', nodeid, None)
        view = self.getview(READWRITE)
        ndx = view.find(id=int(nodeid))
        if ndx < 0:
            raise KeyError, "nodeid %s not found" % nodeid

        row = view[ndx]
        oldvalues = self.uncommitted.setdefault(row.id, {})
        oldval = oldvalues['_isdel'] = row._isdel
        row._isdel = 1

        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, _RETIRE, {})
        if self.key:
            iv = self.getindexview(READWRITE)
            ndx = iv.find(k=getattr(row, self.key))
            # find is broken with multiple attribute lookups
            # on ordered views
            #ndx = iv.find(k=getattr(row, self.key),i=row.id)
            if ndx > -1 and iv[ndx].i == row.id:
                iv.delete(ndx)

        self.db.dirty = 1
        self.fireReactors('retire', nodeid, None)

    def restore(self, nodeid):
        '''Restore a retired node.

        Make node available for all operations like it was before retirement.
        '''
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError, 'Database open read-only'

        # check if key property was overrided
        key = self.getkey()
        keyvalue = self.get(nodeid, key)

        try:
            id = self.lookup(keyvalue)
        except KeyError:
            pass
        else:
            raise KeyError, "Key property (%s) of retired node clashes with \
                existing one (%s)" % (key, keyvalue)
        # Now we can safely restore node
        self.fireAuditors('restore', nodeid, None)
        view = self.getview(READWRITE)
        ndx = view.find(id=int(nodeid))
        if ndx < 0:
            raise KeyError, "nodeid %s not found" % nodeid

        row = view[ndx]
        oldvalues = self.uncommitted.setdefault(row.id, {})
        oldval = oldvalues['_isdel'] = row._isdel
        row._isdel = 0

        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, _RESTORE, {})
        if self.key:
            iv = self.getindexview(READWRITE)
            ndx = iv.find(k=getattr(row, self.key),i=row.id)
            if ndx > -1:
                iv.delete(ndx)
        self.db.dirty = 1
        self.fireReactors('restore', nodeid, None)

    def is_retired(self, nodeid):
        '''Return true if the node is retired
        '''
        view = self.getview(READWRITE)
        # node must exist & not be retired
        id = int(nodeid)
        ndx = view.find(id=id)
        if ndx < 0:
            raise IndexError, "%s has no node %s" % (self.classname, nodeid)
        row = view[ndx]
        return row._isdel

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

    def setkey(self, propname):
        '''Select a String property of this class to be the key property.

        'propname' must be the name of a String property of this class or
        None, or a TypeError is raised.  The values of the key property on
        all existing nodes must be unique or a ValueError is raised.
        '''
        if self.key:
            if propname == self.key:
                return
            else:
                # drop the old key table
                tablename = "_%s.%s"%(self.classname, self.key)
                self.db._db.getas(tablename)

            #raise ValueError, "%s already indexed on %s"%(self.classname,
            #    self.key)

        prop = self.properties.get(propname, None)
        if prop is None:
            prop = self.privateprops.get(propname, None)
        if prop is None:
            raise KeyError, "no property %s" % propname
        if not isinstance(prop, hyperdb.String):
            raise TypeError, "%s is not a String" % propname

        # the way he index on properties is by creating a
        # table named _%(classname)s.%(key)s, if this table
        # exists then everything is okay.  If this table
        # doesn't exist, then generate a new table on the
        # key value.

        # first setkey for this run or key has been changed
        self.key = propname
        tablename = "_%s.%s"%(self.classname, self.key)

        iv = self.db._db.view(tablename)
        if self.db.fastopen and iv.structure():
            return

        # very first setkey ever or the key has changed
        self.db.dirty = 1
        iv = self.db._db.getas('_%s[k:S,i:I]' % tablename)
        iv = iv.ordered(1)
        for row in self.getview():
            iv.append(k=getattr(row, propname), i=row.id)
        self.db.commit()

    def getkey(self):
       '''Return the name of the key property for this class or None.'''
       return self.key

    def lookup(self, keyvalue):
        '''Locate a particular node by its key property and return its id.

        If this class has no key property, a TypeError is raised.  If the
        keyvalue matches one of the values for the key property among
        the nodes in this class, the matching node's id is returned;
        otherwise a KeyError is raised.
        '''
        if not self.key:
            raise TypeError, 'No key property set for class %s'%self.classname

        if type(keyvalue) is not _STRINGTYPE:
            raise TypeError, '%r is not a string'%keyvalue

        # XXX FIX ME -> this is a bit convoluted
        # First we search the index view to get the id
        # which is a quicker look up.
        # Then we lookup the row with id=id
        # if the _isdel property of the row is 0, return the
        # string version of the id. (Why string version???)
        #
        # Otherwise, just lookup the non-indexed key
        # in the non-index table and check the _isdel property
        iv = self.getindexview()
        if iv:
            # look up the index view for the id,
            # then instead of looking up the keyvalue, lookup the
            # quicker id
            ndx = iv.find(k=keyvalue)
            if ndx > -1:
                view = self.getview()
                ndx = view.find(id=iv[ndx].i)
                if ndx > -1:
                    row = view[ndx]
                    if not row._isdel:
                        return str(row.id)
        else:
            # perform the slower query
            view = self.getview()
            ndx = view.find({self.key:keyvalue})
            if ndx > -1:
                row = view[ndx]
                if not row._isdel:
                    return str(row.id)

        raise KeyError, keyvalue

    def destroy(self, id):
        '''Destroy a node.

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
        '''
        view = self.getview(READWRITE)
        ndx = view.find(id=int(id))
        if ndx > -1:
            if self.key:
                keyvalue = getattr(view[ndx], self.key)
                iv = self.getindexview(READWRITE)
                if iv:
                    ivndx = iv.find(k=keyvalue)
                    if ivndx > -1:
                        iv.delete(ivndx)
            view.delete(ndx)
            self.db.destroyjournal(self.classname, id)
            self.db.dirty = 1

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
        for propname, nodeid in propspec:
            # check the prop is OK
            prop = self.ruprops[propname]
            if (not isinstance(prop, hyperdb.Link) and
                    not isinstance(prop, hyperdb.Multilink)):
                raise TypeError, "'%s' not a Link/Multilink property"%propname

        vws = []
        for propname, ids in propspec:
            if type(ids) is _STRINGTYPE:
                ids = {int(ids):1}
            elif ids is None:
                ids = {0:1}
            else:
                d = {}
                for id in ids.keys():
                    if id is None:
                        d[0] = 1
                    else:
                        d[int(id)] = 1
                ids = d
            prop = self.ruprops[propname]
            view = self.getview()
            if isinstance(prop, hyperdb.Multilink):
                def ff(row, nm=propname, ids=ids):
                    if not row._isdel:
                        sv = getattr(row, nm)
                        for sr in sv:
                            if ids.has_key(sr.fid):
                                return 1
                    return 0
            else:
                def ff(row, nm=propname, ids=ids):
                    return not row._isdel and ids.has_key(getattr(row, nm))
            ndxview = view.filter(ff)
            vws.append(ndxview.unique())

        # handle the empty match case
        if not vws:
            return []

        ndxview = vws[0]
        for v in vws[1:]:
            ndxview = ndxview.union(v)
        view = self.getview().remapwith(ndxview)
        rslt = []
        for row in view:
            rslt.append(str(row.id))
        return rslt


    def list(self):
        ''' Return a list of the ids of the active nodes in this class.
        '''
        l = []
        for row in self.getview().select(_isdel=0):
            l.append(str(row.id))
        return l

    def getnodeids(self, retired=None):
        ''' Retrieve all the ids of the nodes for a particular Class.

            Set retired=None to get all nodes. Otherwise it'll get all the
            retired or non-retired nodes, depending on the flag.
        '''
        l = []
        if retired is False or retired is True:
            result = self.getview().select(_isdel=retired)
        else:
            result = self.getview()
        for row in result:
            l.append(str(row.id))
        return l

    def count(self):
        return len(self.getview())

    def getprops(self, protected=1):
        # protected is not in ping's spec
        allprops = self.ruprops.copy()
        if protected and self.privateprops is not None:
            allprops.update(self.privateprops)
        return allprops

    def addprop(self, **properties):
        for key in properties.keys():
            if self.ruprops.has_key(key):
                raise ValueError, "%s is already a property of %s"%(key,
                    self.classname)
        self.ruprops.update(properties)
        # Class structure has changed
        self.db.fastopen = 0
        view = self.__getview()
        self.db.commit()
    # ---- end of ping's spec

    def _filter(self, search_matches, filterspec, proptree):
        '''Return a list of the ids of the active nodes in this class that
        match the 'filter' spec, sorted by the group spec and then the
        sort spec

        "filterspec" is {propname: value(s)}

        "sort" and "group" are (dir, prop) where dir is '+', '-' or None
        and prop is a prop name or None

        "search_matches" is {nodeid: marker} or None

        The filter must match all properties specificed - but if the
        property value to match is a list, any one of the values in the
        list may match for that property to match.
        '''
        if __debug__:
            start_t = time.time()

        where = {'_isdel':0}
        wherehigh = {}
        mlcriteria = {}
        regexes = []
        orcriteria = {}
        for propname, value in filterspec.items():
            prop = self.ruprops.get(propname, None)
            if prop is None:
                prop = self.privateprops[propname]
            if isinstance(prop, hyperdb.Multilink):
                if value in ('-1', ['-1']):
                    value = []
                elif type(value) is not _LISTTYPE:
                    value = [value]
                # transform keys to ids
                u = []
                for item in value:
                    try:
                        item = int(item)
                    except (TypeError, ValueError):
                        item = int(self.db.getclass(prop.classname).lookup(item))
                    if item == -1:
                        item = 0
                    u.append(item)
                mlcriteria[propname] = u
            elif isinstance(prop, hyperdb.Link):
                if type(value) is not _LISTTYPE:
                    value = [value]
                # transform keys to ids
                u = []
                for item in value:
                    if item is None:
                        item = -1
                    else:
                        try:
                            item = int(item)
                        except (TypeError, ValueError):
                            linkcl = self.db.getclass(prop.classname)
                            item = int(linkcl.lookup(item))
                    if item == -1:
                        item = 0
                    u.append(item)
                if len(u) == 1:
                    where[propname] = u[0]
                else:
                    orcriteria[propname] = u
            elif isinstance(prop, hyperdb.String):
                if type(value) is not type([]):
                    value = [value]
                for v in value:
                    # simple glob searching
                    v = re.sub(r'([\|\{\}\\\.\+\[\]\(\)])', r'\\\1', v)
                    v = v.replace('?', '.')
                    v = v.replace('*', '.*?')
                    regexes.append((propname, re.compile(v, re.I)))
            elif propname == 'id':
                where[propname] = int(value)
            elif isinstance(prop, hyperdb.Boolean):
                if type(value) is _STRINGTYPE:
                    bv = value.lower() in ('yes', 'true', 'on', '1')
                else:
                    bv = value
                where[propname] = bv
            elif isinstance(prop, hyperdb.Date):
                try:
                    # Try to filter on range of dates
                    date_rng = prop.range_from_raw (value, self.db)
                    if date_rng.from_value:
                        t = date_rng.from_value.get_tuple()
                        where[propname] = int(calendar.timegm(t))
                    else:
                        # use minimum possible value to exclude items without
                        # 'prop' property
                        where[propname] = 0
                    if date_rng.to_value:
                        t = date_rng.to_value.get_tuple()
                        wherehigh[propname] = int(calendar.timegm(t))
                    else:
                        wherehigh[propname] = None
                except ValueError:
                    # If range creation fails - ignore that search parameter
                    pass
            elif isinstance(prop, hyperdb.Interval):
                try:
                    # Try to filter on range of intervals
                    date_rng = Range(value, date.Interval)
                    if date_rng.from_value:
                        #t = date_rng.from_value.get_tuple()
                        where[propname] = date_rng.from_value.serialise()
                    else:
                        # use minimum possible value to exclude items without
                        # 'prop' property
                        where[propname] = '-99999999999999'
                    if date_rng.to_value:
                        #t = date_rng.to_value.get_tuple()
                        wherehigh[propname] = date_rng.to_value.serialise()
                    else:
                        wherehigh[propname] = None
                except ValueError:
                    # If range creation fails - ignore that search parameter
                    pass
            elif isinstance(prop, hyperdb.Number):
                if type(value) is _LISTTYPE:
                    orcriteria[propname] = [float(v) for v in value]
                else:
                    where[propname] = float(value)
            else:
                where[propname] = str(value)
        v = self.getview()
        if where:
            where_higherbound = where.copy()
            where_higherbound.update(wherehigh)
            v = v.select(where, where_higherbound)

        if mlcriteria:
            # multilink - if any of the nodeids required by the
            # filterspec aren't in this node's property, then skip it
            def ff(row, ml=mlcriteria):
                for propname, values in ml.items():
                    sv = getattr(row, propname)
                    if not values and not sv:
                        return 1
                    for id in values:
                        if sv.find(fid=id) != -1:
                            return 1
                return 0
            iv = v.filter(ff)
            v = v.remapwith(iv)

        if orcriteria:
            def ff(row, crit=orcriteria):
                for propname, allowed in crit.items():
                    val = getattr(row, propname)
                    if val not in allowed:
                        return 0
                return 1

            iv = v.filter(ff)
            v = v.remapwith(iv)

        if regexes:
            def ff(row, r=regexes):
                for propname, regex in r:
                    val = str(getattr(row, propname))
                    if not regex.search(val):
                        return 0
                return 1

            iv = v.filter(ff)
            v = v.remapwith(iv)

        # Handle all the sorting we can inside Metakit. If we encounter
        # transitive attributes or a Multilink on the way, we sort by
        # what we have so far and defer the rest to the outer sorting
        # routine. We mark the attributes for which sorting has been
        # done with sort_done. Of course the whole thing works only if
        # we do it backwards.
        sortspec = []
        rev = []
        sa = []
        if proptree:
            sa = reversed(proptree.sortattr)
        for pt in sa:
            if pt.parent != proptree:
                break;
            propname = pt.name
            dir = pt.sort_direction
            assert (dir and propname)
            isreversed = 0
            if dir == '-':
                isreversed = 1
            try:
                prop = getattr(v, propname)
            except AttributeError:
                logging.getLogger("hyperdb").error(
                    "MK has no property %s" % propname)
                continue
            propclass = self.ruprops.get(propname, None)
            if propclass is None:
                propclass = self.privateprops.get(propname, None)
                if propclass is None:
                    logging.getLogger("hyperdb").error(
                        "Schema has no property %s" % propname)
                    continue
            # Dead code: We dont't find Links here (in sortattr we would
            # see the order property of the link, but this is not in the
            # first level of the tree). The code is left in because one
            # day we might want to properly implement this.  The code is
            # broken because natural-joining to the Link-class can
            # produce name-clashes wich result in broken sorting.
            if isinstance(propclass, hyperdb.Link):
                linkclass = self.db.getclass(propclass.classname)
                lv = linkclass.getview()
                lv = lv.rename('id', propname)
                v = v.join(lv, prop, 1)
                prop = getattr(v, linkclass.orderprop())
            if isreversed:
                rev.append(prop)
            sortspec.append(prop)
            pt.sort_done = True
        sortspec.reverse()
        rev.reverse()
        v = v.sortrev(sortspec, rev)[:] #XXX Metakit bug

        rslt = []
        for row in v:
            id = str(row.id)
            if search_matches is not None:
                if search_matches.has_key(id):
                    rslt.append(id)
            else:
                rslt.append(id)

        if __debug__:
            self.db.stats['filtering'] += (time.time() - start_t)

        return rslt

    def hasnode(self, nodeid):
        '''Determine if the given nodeid actually exists
        '''
        return int(nodeid) < self.maxid

    def stringFind(self, **requirements):
        '''Locate a particular node by matching a set of its String
        properties in a caseless search.

        If the property is not a String property, a TypeError is raised.

        The return is a list of the id of all nodes that match.
        '''
        for propname in requirements.keys():
            prop = self.properties[propname]
            if isinstance(not prop, hyperdb.String):
                raise TypeError, "'%s' not a String property"%propname
            requirements[propname] = requirements[propname].lower()
        requirements['_isdel'] = 0

        l = []
        for row in self.getview().select(requirements):
            l.append(str(row.id))
        return l

    def addjournal(self, nodeid, action, params):
        '''Add a journal to the given nodeid,
        'action' may be:

            'create' or 'set' -- 'params' is a dictionary of property values
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retire' -- 'params' is None
        '''
        self.db.addjournal(self.classname, nodeid, action, params)

    def index(self, nodeid):
        ''' Add (or refresh) the node to search indexes '''
        # find all the String properties that have indexme
        for prop, propclass in self.getprops().items():
            if isinstance(propclass, hyperdb.String) and propclass.indexme:
                # index them under (classname, nodeid, property)
                self.db.indexer.add_text((self.classname, nodeid, prop),
                                str(self.get(nodeid, prop)))

    # --- used by Database
    def _commit(self):
        ''' called post commit of the DB.
            interested subclasses may override '''
        self.uncommitted = {}
        for action in self.comactions:
            action()
        self.comactions = []
        self.rbactions = []
        self.idcache = {}
    def _rollback(self):
        ''' called pre rollback of the DB.
            interested subclasses may override '''
        self.comactions = []
        for action in self.rbactions:
            action()
        self.rbactions = []
        self.uncommitted = {}
        self.idcache = {}
    def _clear(self):
        view = self.getview(READWRITE)
        if len(view):
            view[:] = []
            self.db.dirty = 1
        iv = self.getindexview(READWRITE)
        if iv:
            iv[:] = []
    def commitaction(self, action):
        ''' call this to register a callback called on commit
            callback is removed on end of transaction '''
        self.comactions.append(action)
    def rollbackaction(self, action):
        ''' call this to register a callback called on rollback
            callback is removed on end of transaction '''
        self.rbactions.append(action)
    # --- internal
    def __getview(self):
        ''' Find the interface for a specific Class in the hyperdb.

            This method checks to see whether the schema has changed and
            re-works the underlying metakit structure if it has.
        '''
        db = self.db._db
        view = db.view(self.classname)
        mkprops = view.structure()

        # if we have structure in the database, and the structure hasn't
        # changed
        # note on view.ordered ->
        # return a metakit view ordered on the id column
        # id is always the first column.  This speeds up
        # look-ups on the id column.

        if mkprops and self.db.fastopen:
            return view.ordered(1)

        # is the definition the same?
        for nm, rutyp in self.ruprops.items():
            for mkprop in mkprops:
                if mkprop.name == nm:
                    break
            else:
                mkprop = None
            if mkprop is None:
                break
            if _typmap[rutyp.__class__] != mkprop.type:
                break
        else:
            # make sure we have the 'actor' property too
            for mkprop in mkprops:
                if mkprop.name == 'actor':
                    return view.ordered(1)

        # The schema has changed.  We need to create or restructure the mk view
        # id comes first, so we can use view.ordered(1) so that
        # MK will order it for us to allow binary-search quick lookups on
        # the id column
        self.db.dirty = 1
        s = ["%s[id:I" % self.classname]

        # these columns will always be added, we can't trample them :)
        _columns = {"id":"I", "_isdel":"I", "activity":"I", "actor": "I",
            "creation":"I", "creator":"I"}

        for nm, rutyp in self.ruprops.items():
            mktyp = _typmap[rutyp.__class__].upper()
            if nm in _columns and _columns[nm] != mktyp:
                # oops, two columns with the same name and different properties
               raise MKBackendError("column %s for table %sis defined with multiple types"%(nm, self.classname))
            _columns[nm] = mktyp
            s.append('%s:%s' % (nm, mktyp))
            if mktyp == 'V':
                s[-1] += ('[fid:I]')

        # XXX FIX ME -> in some tests, creation:I becomes creation:S is this
        # okay?  Does this need to be supported?
        s.append('_isdel:I,activity:I,actor:I,creation:I,creator:I]')
        view = self.db._db.getas(','.join(s))
        self.db.commit()
        return view.ordered(1)
    def getview(self, RW=0):
        # XXX FIX ME -> The RW flag doesn't do anything.
        return self.db._db.view(self.classname).ordered(1)
    def getindexview(self, RW=0):
        # XXX FIX ME -> The RW flag doesn't do anything.
        tablename = "_%s.%s"%(self.classname, self.key)
        return self.db._db.view("_%s" % tablename).ordered(1)

    #
    # import / export
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
            journal should be initialised using the "creator" and "creation"
            information.

            Return the nodeid of the node imported.
        '''
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError, 'Database open read-only'
        properties = self.getprops()

        d = {}
        view = self.getview(READWRITE)
        for i in range(len(propnames)):
            value = eval(proplist[i])
            if not value:
                continue

            propname = propnames[i]
            if propname == 'id':
                newid = value = int(value)
            elif propname == 'is retired':
                # is the item retired?
                if int(value):
                    d['_isdel'] = 1
                continue
            elif value is None:
                d[propname] = None
                continue

            prop = properties[propname]
            if isinstance(prop, hyperdb.Date):
                value = int(calendar.timegm(value))
            elif isinstance(prop, hyperdb.Interval):
                value = date.Interval(value).serialise()
            elif isinstance(prop, hyperdb.Number):
                value = float(value)
            elif isinstance(prop, hyperdb.Boolean):
                value = int(value)
            elif isinstance(prop, hyperdb.Link) and value:
                value = int(value)
            elif isinstance(prop, hyperdb.Multilink):
                # we handle multilinks separately
                continue
            d[propname] = value

        # possibly make a new node
        if not d.has_key('id'):
            d['id'] = newid = self.maxid
            self.maxid += 1

        # save off the node
        view.append(d)

        # fix up multilinks
        ndx = view.find(id=newid)
        row = view[ndx]
        for i in range(len(propnames)):
            value = eval(proplist[i])
            propname = propnames[i]
            if propname == 'is retired':
                continue
            prop = properties[propname]
            if not isinstance(prop, hyperdb.Multilink):
                continue
            sv = getattr(row, propname)
            for entry in value:
                sv.append((int(entry),))

        self.db.dirty = 1
        return newid

    def export_journals(self):
        '''Export a class's journal - generate a list of lists of
        CSV-able data:

            nodeid, date, user, action, params

        No heading here - the columns are fixed.
        '''
        from roundup.hyperdb import Interval, Date, Password
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
                            pass
                        elif isinstance(prop, Date):
                            value = value.get_tuple()
                        elif isinstance(prop, Interval):
                            value = value.get_tuple()
                        elif isinstance(prop, Password):
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
            jdate = int(calendar.timegm(date.Date(jdate).get_tuple()))
            r = d.setdefault(nodeid, [])
            if action == 'set':
                for propname, value in params.items():
                    prop = properties[propname]
                    if value is None:
                        pass
                    elif isinstance(prop, hyperdb.Date):
                        value = date.Date(value)
                    elif isinstance(prop, hyperdb.Interval):
                        value = date.Interval(value)
                    elif isinstance(prop, hyperdb.Password):
                        pwd = password.Password()
                        pwd.unpack(value)
                        value = pwd
                    params[propname] = value
            action = _names_to_actionnames[action]
            r.append((nodeid, jdate, user, action, params))

        for nodeid, l in d.items():
            self.db.setjournal(self.classname, nodeid, l)

def _fetchML(sv):
    l = []
    for row in sv:
        if row.fid:
            l.append(str(row.fid))
    return l

def _fetchPW(s):
    ''' Convert to a password.Password unless the password is '' which is
        our sentinel for "unset".
    '''
    if s == '':
        return None
    p = password.Password()
    p.unpack(s)
    return p

def _fetchLink(n):
    ''' Return None if the link is 0 - otherwise strify it.
    '''
    return n and str(n) or None

def _fetchDate(n):
    ''' Convert the timestamp to a date.Date instance - unless it's 0 which
        is our sentinel for "unset".
    '''
    if n == 0:
        return None
    return date.Date(time.gmtime(n))

def _fetchInterval(n):
    ''' Convert to a date.Interval unless the interval is '' which is our
        sentinel for "unset".
    '''
    if n == '':
        return None
    return date.Interval(n)

# Converters for boolean and numbers to properly
# return None values.
# These are in conjunction with the setters above
#  look for hyperdb.Boolean and hyperdb.Number
if BACKWARDS_COMPATIBLE:
    def getBoolean(bool): return bool
    def getNumber(number): return number
else:
    def getBoolean(bool):
        if not bool: res = None
        else: res = bool - 1
        return res

    def getNumber(number):
        if number == 0: res = None
        elif number < 0: res = number
        else: res = number - 1
        return res

_converters = {
    hyperdb.Date   : _fetchDate,
    hyperdb.Link   : _fetchLink,
    hyperdb.Multilink : _fetchML,
    hyperdb.Interval  : _fetchInterval,
    hyperdb.Password  : _fetchPW,
    hyperdb.Boolean   : getBoolean,
    hyperdb.Number    : getNumber,
    hyperdb.String    : lambda s: s and str(s) or None,
}

class FileName(hyperdb.String):
    isfilename = 1

_typmap = {
    FileName : 'S',
    hyperdb.String : 'S',
    hyperdb.Date   : 'I',
    hyperdb.Link   : 'I',
    hyperdb.Multilink : 'V',
    hyperdb.Interval  : 'S',
    hyperdb.Password  : 'S',
    hyperdb.Boolean   : 'I',
    hyperdb.Number    : 'D',
}
class FileClass(hyperdb.FileClass, Class):
    ''' like Class but with a content property
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

    def gen_filename(self, nodeid):
        nm = '%s%s' % (self.classname, nodeid)
        sd = str(int(int(nodeid) / 1000))
        d = os.path.join(self.db.config.DATABASE, 'files', self.classname, sd)
        if not os.path.exists(d):
            os.makedirs(d)
        return os.path.join(d, nm)

    def export_files(self, dirname, nodeid):
        ''' Export the "content" property as a file, not csv column
        '''
        source = self.gen_filename(nodeid)
        x, filename = os.path.split(source)
        x, subdir = os.path.split(x)
        dest = os.path.join(dirname, self.classname+'-files', subdir, filename)
        if not os.path.exists(os.path.dirname(dest)):
            os.makedirs(os.path.dirname(dest))
        shutil.copyfile(source, dest)

    def import_files(self, dirname, nodeid):
        ''' Import the "content" property as a file
        '''
        dest = self.gen_filename(nodeid)
        x, filename = os.path.split(dest)
        x, subdir = os.path.split(x)
        source = os.path.join(dirname, self.classname+'-files', subdir,
            filename)
        if not os.path.exists(os.path.dirname(dest)):
            os.makedirs(os.path.dirname(dest))
        shutil.copyfile(source, dest)

        if self.properties['content'].indexme:
            return

        mime_type = None
        if self.getprops().has_key('type'):
            mime_type = self.get(nodeid, 'type')
        if not mime_type:
            mime_type = self.default_mime_type
        self.db.indexer.add_text((self.classname, nodeid, 'content'),
            self.get(nodeid, 'content'), mime_type)

    def get(self, nodeid, propname, default=_marker, cache=1):
        if propname == 'content':
            poss_msg = 'Possibly an access right configuration problem.'
            fnm = self.gen_filename(nodeid)
            if not os.path.exists(fnm):
                fnm = fnm + '.tmp'
            try:
                f = open(fnm, 'rb')
            except IOError, (strerror):
                # XXX by catching this we donot see an error in the log.
                return 'ERROR reading file: %s%s\n%s\n%s'%(
                        self.classname, nodeid, poss_msg, strerror)
            x = f.read()
            f.close()
        else:
            x = Class.get(self, nodeid, propname, default)
        return x

    def create(self, **propvalues):
        if not propvalues:
            raise ValueError, "Need something to create!"
        self.fireAuditors('create', None, propvalues)

        content = propvalues['content']
        del propvalues['content']

        newid = Class.create_inner(self, **propvalues)
        if not content:
            return newid

        # figure a filename
        nm = self.gen_filename(newid)

        # make sure we don't register the rename action more than once
        if not os.path.exists(nm + '.tmp'):
            # register commit and rollback actions
            def commit(fnm=nm):
                os.rename(fnm + '.tmp', fnm)
            self.commitaction(commit)
            def undo(fnm=nm):
                os.remove(fnm + '.tmp')
            self.rollbackaction(undo)

        # save the tempfile
        f = open(nm + '.tmp', 'wb')
        f.write(content)
        f.close()

        if not self.properties['content'].indexme:
            return newid

        mimetype = propvalues.get('type', self.default_mime_type)
        self.db.indexer.add_text((self.classname, newid, 'content'), content,
            mimetype)
        return newid

    def set(self, itemid, **propvalues):
        if not propvalues:
            return
        self.fireAuditors('set', None, propvalues)

        content = propvalues.get('content', None)
        if content is not None:
            del propvalues['content']

        propvalues, oldnode = Class.set_inner(self, itemid, **propvalues)

        # figure a filename
        if content is not None:
            nm = self.gen_filename(itemid)

            # make sure we don't register the rename action more than once
            if not os.path.exists(nm + '.tmp'):
                # register commit and rollback actions
                def commit(fnm=nm):
                    if os.path.exists(fnm):
                        os.remove(fnm)
                    os.rename(fnm + '.tmp', fnm)
                self.commitaction(commit)
                def undo(fnm=nm):
                    os.remove(fnm + '.tmp')
                self.rollbackaction(undo)

            f = open(nm + '.tmp', 'wb')
            f.write(content)
            f.close()

            if self.properties['content'].indexme:
                mimetype = propvalues.get('type', self.default_mime_type)
                self.db.indexer.add_text((self.classname, itemid, 'content'),
                    content, mimetype)

        self.fireReactors('set', oldnode, propvalues)

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

class IssueClass(Class, roundupdb.IssueClass):
    ''' The newly-created class automatically includes the "messages",
        "files", "nosy", and "superseder" properties.  If the 'properties'
        dictionary attempts to specify any of these properties or a
        "creation" or "activity" property, a ValueError is raised.
    '''
    def __init__(self, db, classname, **properties):
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

CURVERSION = 2

class MetakitIndexer(CommonIndexer):
    def __init__(self, db):
        CommonIndexer.__init__(self, db)
        self.path = os.path.join(db.config.DATABASE, 'index.mk4')
        self.db = metakit.storage(self.path, 1)
        self.datadb = db._db
        self.reindex = 0
        v = self.db.view('version')
        if not v.structure():
            v = self.db.getas('version[vers:I]')
            self.db.commit()
            v.append(vers=CURVERSION)
            self.reindex = 1
        elif v[0].vers != CURVERSION:
            v[0].vers = CURVERSION
            self.reindex = 1
        if self.reindex:
            self.db.getas('ids[tblid:I,nodeid:I,propid:I,ignore:I]')
            self.db.getas('index[word:S,hits[pos:I]]')
            self.db.commit()
            self.reindex = 1
        self.changed = 0
        self.propcache = {}

    def close(self):
        '''close the indexing database'''
        del self.db
        self.db = None

    def force_reindex(self):
        '''Force a reindexing of the database.  This essentially
        empties the tables ids and index and sets a flag so
        that the databases are reindexed'''
        v = self.db.view('ids')
        v[:] = []
        v = self.db.view('index')
        v[:] = []
        self.db.commit()
        self.reindex = 1

    def should_reindex(self):
        '''returns True if the indexes need to be rebuilt'''
        return self.reindex

    def _getprops(self, classname):
        props = self.propcache.get(classname, None)
        if props is None:
            props = self.datadb.view(classname).structure()
            props = [prop.name for prop in props]
            self.propcache[classname] = props
        return props

    def _getpropid(self, classname, propname):
        return self._getprops(classname).index(propname)

    def _getpropname(self, classname, propid):
        return self._getprops(classname)[propid]

    def add_text(self, identifier, text, mime_type='text/plain'):
        if mime_type != 'text/plain':
            return
        classname, nodeid, property = identifier
        tbls = self.datadb.view('tables')
        tblid = tbls.find(name=classname)
        if tblid < 0:
            raise KeyError, "unknown class %r"%classname
        nodeid = int(nodeid)
        propid = self._getpropid(classname, property)
        ids = self.db.view('ids')
        oldpos = ids.find(tblid=tblid,nodeid=nodeid,propid=propid,ignore=0)
        if oldpos > -1:
            ids[oldpos].ignore = 1
            self.changed = 1
        pos = ids.append(tblid=tblid,nodeid=nodeid,propid=propid)

        wordlist = re.findall(r'\b\w{2,25}\b', text.upper())
        words = {}
        for word in wordlist:
            if not self.is_stopword(word):
                words[word] = 1
        words = words.keys()

        index = self.db.view('index').ordered(1)
        for word in words:
            ndx = index.find(word=word)
            if ndx < 0:
                index.append(word=word)
                ndx = index.find(word=word)
            index[ndx].hits.append(pos=pos)
            self.changed = 1

    def find(self, wordlist):
        '''look up all the words in the wordlist.
        If none are found return an empty dictionary
        * more rules here
        '''
        hits = None
        index = self.db.view('index').ordered(1)
        for word in wordlist:
            word = word.upper()
            if not 2 < len(word) < 26:
                continue
            ndx = index.find(word=word)
            if ndx < 0:
                return {}
            if hits is None:
                hits = index[ndx].hits
            else:
                hits = hits.intersect(index[ndx].hits)
            if len(hits) == 0:
                return {}
        if hits is None:
            return []
        rslt = []
        ids = self.db.view('ids').remapwith(hits)
        tbls = self.datadb.view('tables')
        for i in range(len(ids)):
            hit = ids[i]
            if not hit.ignore:
                classname = tbls[hit.tblid].name
                nodeid = str(hit.nodeid)
                property = self._getpropname(classname, hit.propid)
                rslt.append((classname, nodeid, property))
        return rslt

    def save_index(self):
        if self.changed:
            self.db.commit()
        self.changed = 0

    def rollback(self):
        if self.changed:
            self.db.rollback()
            self.db = metakit.storage(self.path, 1)
        self.changed = 0

try:
    from indexer_xapian import Indexer
except ImportError:
    Indexer = MetakitIndexer

# vim: set et sts=4 sw=4 :
