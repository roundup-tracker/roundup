'''
   Metakit backend for Roundup, originally by Gordon McMillan.

   Notes by Richard:

   This backend has some behaviour specific to metakit:

    - there's no concept of an explicit "unset" in metakit, so all types
      have some "unset" value:

      ========= ===== ====================================================
      Type      Value Action when fetching from mk
      ========= ===== ====================================================
      Strings   ''    convert to None
      Date      0     (seconds since 1970-01-01.00:00:00) convert to None
      Interval  ''    convert to None
      Number    0     ambiguious :( - do nothing
      Boolean   0     ambiguious :( - do nothing
      Link      ''    convert to None
      Multilink []    actually, mk can handle this one ;)
      Passowrd  ''    convert to None
      ========= ===== ====================================================

      The get/set routines handle these values accordingly by converting
      to/from None where they can. The Number/Boolean types are not able
      to handle an "unset" at all, so they default the "unset" to 0.

    - probably a bunch of stuff that I'm not aware of yet because I haven't
      fully read through the source. One of these days....
'''
from roundup import hyperdb, date, password, roundupdb, security
import metakit
from sessions import Sessions, OneTimeKeys
import re, marshal, os, sys, weakref, time, calendar
from roundup import indexer
import locking

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
        try:
            delattr(db, 'curuserid')
        except AttributeError:
            pass
    return db

class _Database(hyperdb.Database, roundupdb.Database):
    def __init__(self, config, journaltag=None):
        self.config = config
        self.journaltag = journaltag
        self.classes = {}
        self.dirty = 0
        self.lockfile = None
        self._db = self.__open()
        self.indexer = Indexer(self.config.DATABASE, self._db)
        self.sessions = Sessions(self.config)
        self.otks = OneTimeKeys(self.config)
        self.security = security.Security(self)

        os.umask(0002)

    def post_init(self):
        if self.indexer.should_reindex():
            self.reindex()

    def reindex(self):
        for klass in self.classes.values():
            for nodeid in klass.list():
                klass.index(nodeid)
        self.indexer.save_index()

    # --- defined in ping's spec
    def __getattr__(self, classname):
        if classname == 'curuserid':
            if self.journaltag is None:
                return None

            # try to set the curuserid from the journaltag
            try:
                x = int(self.classes['user'].lookup(self.journaltag))
                self.curuserid = x
            except KeyError:
                if self.journaltag == 'admin':
                    self.curuserid = x = 1
                else:
                    x = 0
            return x
        elif classname == 'transactions':
            return self.dirty
        # fall back on the classes
        return self.getclass(classname)
    def getclass(self, classname):
        try:
            return self.classes[classname]
        except KeyError:
            raise KeyError, 'There is no class called "%s"'%classname
    def getclasses(self):
        return self.classes.keys()
    # --- end of ping's spec 

    # --- exposed methods
    def commit(self):
        if self.dirty:
            self._db.commit()
            for cl in self.classes.values():
                cl._commit()
            self.indexer.save_index()
        self.dirty = 0
    def rollback(self):
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
        for cl in self.classes.values():
            cl._commit()
    def clear(self):
        for cl in self.classes.values():
            cl._clear()
    def hasnode(self, classname, nodeid):
        return self.getclass(classname).hasnode(nodeid)
    def pack(self, pack_before):
        mindate = int(calendar.timegm(pack_before.get_tuple()))
        i = 0
        while i < len(self.hist):
            if self.hist[i].date < mindate and self.hist[i].action != _CREATE:
                self.hist.delete(i)
            else:
                i = i + 1
    def addclass(self, cl):
        self.classes[cl.classname] = cl
        if self.tables.find(name=cl.classname) < 0:
            self.tables.append(name=cl.classname)
    def addjournal(self, tablenm, nodeid, action, params, creator=None,
                creation=None):
        tblid = self.tables.find(name=tablenm)
        if tblid == -1:
            tblid = self.tables.append(name=tablenm)
        if creator is None:
            creator = self.curuserid
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
                         user = creator,
                         params = marshal.dumps(params))
    def getjournal(self, tablenm, nodeid):
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
                print "history couldn't unmarshal %r" % row.params
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
            pkgnm = self.config.__name__.split('.')[0]
            schemamod = sys.modules.get(pkgnm+'.dbinit', None)
            if schemamod:
                if os.path.exists(schemamod.__file__):
                    schematm = os.path.getmtime(schemamod.__file__)
                    if schematm < dbtm:
                        # found schema mod - it's older than the db
                        self.fastopen = 1
                else:
                     # can't find schemamod - must be frozen
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
        pass
        
_STRINGTYPE = type('')
_LISTTYPE = type([])
_CREATE, _SET, _RETIRE, _LINK, _UNLINK = range(5)

_actionnames = {
    _CREATE : 'create',
    _SET : 'set',
    _RETIRE : 'retire',
    _LINK : 'link',
    _UNLINK : 'unlink',
}

_marker = []

_ALLOWSETTINGPRIVATEPROPS = 0

class Class:    
    privateprops = None
    def __init__(self, db, classname, **properties):
        #self.db = weakref.proxy(db)
        self.db = db
        self.classname = classname
        self.keyname = None
        self.ruprops = properties
        self.privateprops = { 'id' : hyperdb.String(),
                              'activity' : hyperdb.Date(),
                              'creation' : hyperdb.Date(),
                              'creator'  : hyperdb.Link('user') }

        # event -> list of callables
        self.auditors = {'create': [], 'set': [], 'retire': []}
        self.reactors = {'create': [], 'set': [], 'retire': []}

        view = self.__getview()
        self.maxid = 1
        if view:
            self.maxid = view[-1].id + 1
        self.uncommitted = {}
        self.rbactions = []

        # people reach inside!!
        self.properties = self.ruprops
        self.db.addclass(self)
        self.idcache = {}

        # default is to journal changes
        self.do_journal = 1

    def enableJournalling(self):
        '''Turn journalling on for this class
        '''
        self.do_journal = 1

    def disableJournalling(self):
        '''Turn journalling off for this class
        '''
        self.do_journal = 0
        
    # --- the roundup.Class methods
    def audit(self, event, detector):
        l = self.auditors[event]
        if detector not in l:
            self.auditors[event].append(detector)
    def fireAuditors(self, action, nodeid, newvalues):
        for audit in self.auditors[action]:
            audit(self.db, self, nodeid, newvalues)
    def fireReactors(self, action, nodeid, oldvalues):
        for react in self.reactors[action]:
            react(self.db, self, nodeid, oldvalues)
    def react(self, event, detector):
        l = self.reactors[event]
        if detector not in l:
            self.reactors[event].append(detector)

    # --- the hyperdb.Class methods
    def create(self, **propvalues):
        self.fireAuditors('create', None, propvalues)
        newid = self.create_inner(**propvalues)
        # self.set() (called in self.create_inner()) does reactors)
        return newid

    def create_inner(self, **propvalues):
        rowdict = {}
        rowdict['id'] = newid = self.maxid
        self.maxid += 1
        ndx = self.getview(1).append(rowdict)
        propvalues['#ISNEW'] = 1
        try:
            self.set(str(newid), **propvalues)
        except Exception:
            self.maxid -= 1
            raise
        return str(newid)
    
    def get(self, nodeid, propname, default=_marker, cache=1):
        # default and cache aren't in the spec
        # cache=0 means "original value"

        view = self.getview()        
        id = int(nodeid)
        if cache == 0:
            oldnode = self.uncommitted.get(id, None)
            if oldnode and oldnode.has_key(propname):
                return oldnode[propname]
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
        isnew = 0
        if propvalues.has_key('#ISNEW'):
            isnew = 1
            del propvalues['#ISNEW']
        if not isnew:
            self.fireAuditors('set', nodeid, propvalues)
        if not propvalues:
            return propvalues
        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError, 'Database open read-only'
        view = self.getview(1)

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
            if key == self.keyname:
                iv = self.getindexview(1)
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
                changes[key] = str(oldvalue)
                propvalues[key] = str(value)

            elif isinstance(prop, hyperdb.Interval):
                if value is not None and not isinstance(value, date.Interval):
                    raise TypeError, 'new property "%s" not an Interval'% key
                if value is None:
                    setattr(row, key, '')
                else:
                    setattr(row, key, str(value))
                changes[key] = str(oldvalue)
                propvalues[key] = str(value)
                
            elif isinstance(prop, hyperdb.Number):
                if value is None:
                    value = 0
                try:
                    v = int(value)
                except ValueError:
                    raise TypeError, "%s (%s) is not numeric"%(key, repr(value))
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
                setattr(row, key, bv)
                changes[key] = oldvalue
                propvalues[key] = value

            oldnode[key] = oldvalue

        # nothing to do?
        if not propvalues:
            return propvalues
        if not propvalues.has_key('activity'):
            row.activity = int(time.time())
        if isnew:
            if not row.creation:
                row.creation = int(time.time())
            if not row.creator:
                row.creator = self.db.curuserid

        self.db.dirty = 1
        if self.do_journal:
            if isnew:
                self.db.addjournal(self.classname, nodeid, _CREATE, {})
                self.fireReactors('create', nodeid, None)
            else:
                self.db.addjournal(self.classname, nodeid, _SET, changes)
                self.fireReactors('set', nodeid, oldnode)

        return propvalues
    
    def retire(self, nodeid):
        if self.db.journaltag is None:
            raise hyperdb.DatabaseError, 'Database open read-only'
        self.fireAuditors('retire', nodeid, None)
        view = self.getview(1)
        ndx = view.find(id=int(nodeid))
        if ndx < 0:
            raise KeyError, "nodeid %s not found" % nodeid

        row = view[ndx]
        oldvalues = self.uncommitted.setdefault(row.id, {})
        oldval = oldvalues['_isdel'] = row._isdel
        row._isdel = 1

        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, _RETIRE, {})
        if self.keyname:
            iv = self.getindexview(1)
            ndx = iv.find(k=getattr(row, self.keyname),i=row.id)
            if ndx > -1:
                iv.delete(ndx)
        self.db.dirty = 1
        self.fireReactors('retire', nodeid, None)

    def is_retired(self, nodeid):
        view = self.getview(1)
        # node must exist & not be retired
        id = int(nodeid)
        ndx = view.find(id=id)
        if ndx < 0:
            raise IndexError, "%s has no node %s" % (self.classname, nodeid)
        row = view[ndx]
        return row._isdel

    def history(self, nodeid):
        if not self.do_journal:
            raise ValueError, 'Journalling is disabled for this class'
        return self.db.getjournal(self.classname, nodeid)

    def setkey(self, propname):
        if self.keyname:
            if propname == self.keyname:
                return
            raise ValueError, "%s already indexed on %s"%(self.classname,
                self.keyname)
        prop = self.properties.get(propname, None)
        if prop is None:
            prop = self.privateprops.get(propname, None)
        if prop is None:
            raise KeyError, "no property %s" % propname
        if not isinstance(prop, hyperdb.String):
            raise TypeError, "%s is not a String" % propname

        # first setkey for this run
        self.keyname = propname
        iv = self.db._db.view('_%s' % self.classname)
        if self.db.fastopen and iv.structure():
            return

        # very first setkey ever
        self.db.dirty = 1
        iv = self.db._db.getas('_%s[k:S,i:I]' % self.classname)
        iv = iv.ordered(1)
        for row in self.getview():
            iv.append(k=getattr(row, propname), i=row.id)
        self.db.commit()

    def getkey(self):
        return self.keyname

    def lookup(self, keyvalue):
        if type(keyvalue) is not _STRINGTYPE:
            raise TypeError, "%r is not a string" % keyvalue
        iv = self.getindexview()
        if iv:
            ndx = iv.find(k=keyvalue)
            if ndx > -1:
                return str(iv[ndx].i)
        else:
            view = self.getview()
            ndx = view.find({self.keyname:keyvalue, '_isdel':0})
            if ndx > -1:
                return str(view[ndx].id)
        raise KeyError, keyvalue

    def destroy(self, id):
        view = self.getview(1)
        ndx = view.find(id=int(id))
        if ndx > -1:
            if self.keyname:
                keyvalue = getattr(view[ndx], self.keyname)
                iv = self.getindexview(1)
                if iv:
                    ivndx = iv.find(k=keyvalue)
                    if ivndx > -1:
                        iv.delete(ivndx)
            view.delete(ndx)
            self.db.destroyjournal(self.classname, id)
            self.db.dirty = 1
        
    def find(self, **propspec):
        """Get the ids of nodes in this class which link to the given nodes.

        'propspec' consists of keyword args propname={nodeid:1,}   
        'propname' must be the name of a property in this class, or a
                   KeyError is raised.  That property must be a Link or
                   Multilink property, or a TypeError is raised.

        Any node in this class whose propname property links to any of the
        nodeids will be returned. Used by the full text indexing, which knows
        that "foo" occurs in msg1, msg3 and file7; so we have hits on these
        issues:

            db.issue.find(messages={'1':1,'3':1}, files={'7':1})

        """
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
            else:
                d = {}
                for id in ids.keys():
                    d[int(id)] = 1
                ids = d
            prop = self.ruprops[propname]
            view = self.getview()
            if isinstance(prop, hyperdb.Multilink):
                def ff(row, nm=propname, ids=ids):
                    sv = getattr(row, nm)
                    for sr in sv:
                        if ids.has_key(sr.fid):
                            return 1
                    return 0
            else:
                def ff(row, nm=propname, ids=ids):
                    return ids.has_key(getattr(row, nm))
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
        l = []
        for row in self.getview().select(_isdel=0):
            l.append(str(row.id))
        return l

    def getnodeids(self):
        l = []
        for row in self.getview():
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

    def filter(self, search_matches, filterspec, sort=(None,None),
            group=(None,None)):
        # search_matches is None or a set (dict of {nodeid: {propname:[nodeid,...]}})
        # filterspec is a dict {propname:value}
        # sort and group are (dir, prop) where dir is '+', '-' or None
        #                    and prop is a prop name or None
        where = {'_isdel':0}
        mlcriteria = {}
        regexes = {}
        orcriteria = {}
        for propname, value in filterspec.items():
            prop = self.ruprops.get(propname, None)
            if prop is None:
                prop = self.privateprops[propname]
            if isinstance(prop, hyperdb.Multilink):
                if type(value) is not _LISTTYPE:
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
                    try:
                        item = int(item)
                    except (TypeError, ValueError):
                        item = int(self.db.getclass(prop.classname).lookup(item))
                    if item == -1:
                        item = 0
                    u.append(item)
                if len(u) == 1:
                    where[propname] = u[0]
                else:
                    orcriteria[propname] = u
            elif isinstance(prop, hyperdb.String):
                # simple glob searching
                v = re.sub(r'([\|\{\}\\\.\+\[\]\(\)])', r'\\\1', value)
                v = v.replace('?', '.')
                v = v.replace('*', '.*?')
                regexes[propname] = re.compile(v, re.I)
            elif propname == 'id':
                where[propname] = int(value)
            elif isinstance(prop, hyperdb.Boolean):
                if type(value) is _STRINGTYPE:
                    bv = value.lower() in ('yes', 'true', 'on', '1')
                else:
                    bv = value
                where[propname] = bv
            elif isinstance(prop, hyperdb.Date):
                t = date.Date(value).get_tuple()
                where[propname] = int(calendar.timegm(t))
            elif isinstance(prop, hyperdb.Interval):
                where[propname] = str(date.Interval(value))
            elif isinstance(prop, hyperdb.Number):
                where[propname] = int(value)
            else:
                where[propname] = str(value)
        v = self.getview()
        #print "filter start at  %s" % time.time() 
        if where:
            v = v.select(where)
        #print "filter where at  %s" % time.time() 

        if mlcriteria:
            # multilink - if any of the nodeids required by the
            # filterspec aren't in this node's property, then skip it
            def ff(row, ml=mlcriteria):
                for propname, values in ml.items():
                    sv = getattr(row, propname)
                    for id in values:
                        if sv.find(fid=id) == -1:
                            return 0
                return 1
            iv = v.filter(ff)
            v = v.remapwith(iv)

        #print "filter mlcrit at %s" % time.time() 
        
        if orcriteria:
            def ff(row, crit=orcriteria):
                for propname, allowed in crit.items():
                    val = getattr(row, propname)
                    if val not in allowed:
                        return 0
                return 1
            
            iv = v.filter(ff)
            v = v.remapwith(iv)
        
        #print "filter orcrit at %s" % time.time() 
        if regexes:
            def ff(row, r=regexes):
                for propname, regex in r.items():
                    val = str(getattr(row, propname))
                    if not regex.search(val):
                        return 0
                return 1
            
            iv = v.filter(ff)
            v = v.remapwith(iv)
        #print "filter regexs at %s" % time.time() 
        
        if sort or group:
            sortspec = []
            rev = []
            for dir, propname in group, sort:
                if propname is None: continue
                isreversed = 0
                if dir == '-':
                    isreversed = 1
                try:
                    prop = getattr(v, propname)
                except AttributeError:
                    print "MK has no property %s" % propname
                    continue
                propclass = self.ruprops.get(propname, None)
                if propclass is None:
                    propclass = self.privateprops.get(propname, None)
                    if propclass is None:
                        print "Schema has no property %s" % propname
                        continue
                if isinstance(propclass, hyperdb.Link):
                    linkclass = self.db.getclass(propclass.classname)
                    lv = linkclass.getview()
                    lv = lv.rename('id', propname)
                    v = v.join(lv, prop, 1)
                    if linkclass.getprops().has_key('order'):
                        propname = 'order'
                    else:
                        propname = linkclass.labelprop()
                    prop = getattr(v, propname)
                if isreversed:
                    rev.append(prop)
                sortspec.append(prop)
            v = v.sortrev(sortspec, rev)[:] #XXX Metakit bug
        #print "filter sort   at %s" % time.time() 
            
        rslt = []
        for row in v:
            id = str(row.id)
            if search_matches is not None:
                if search_matches.has_key(id):
                    rslt.append(id)
            else:
                rslt.append(id)
        return rslt
    
    def hasnode(self, nodeid):
        return int(nodeid) < self.maxid
    
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

    def stringFind(self, **requirements):
        """Locate a particular node by matching a set of its String
        properties in a caseless search.

        If the property is not a String property, a TypeError is raised.
        
        The return is a list of the id of all nodes that match.
        """
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
        self.db.addjournal(self.classname, nodeid, action, params)

    def index(self, nodeid):
        ''' Add (or refresh) the node to search indexes '''
        # find all the String properties that have indexme
        for prop, propclass in self.getprops().items():
            if isinstance(propclass, hyperdb.String) and propclass.indexme:
                # index them under (classname, nodeid, property)
                self.db.indexer.add_text((self.classname, nodeid, prop),
                                str(self.get(nodeid, prop)))

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
        l.append(self.is_retired(nodeid))

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
        view = self.getview(1)
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

            prop = properties[propname]
            if isinstance(prop, hyperdb.Date):
                value = int(calendar.timegm(value))
            elif isinstance(prop, hyperdb.Interval):
                value = str(date.Interval(value))
            elif isinstance(prop, hyperdb.Number):
                value = int(value)
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
                sv.append(int(entry))

        self.db.dirty = 1
        creator = d.get('creator', 0)
        creation = d.get('creation', 0)
        self.db.addjournal(self.classname, str(newid), _CREATE, {}, creator,
            creation)
        return newid

    # --- used by Database
    def _commit(self):
        """ called post commit of the DB.
            interested subclasses may override """
        self.uncommitted = {}
        self.rbactions = []
        self.idcache = {}
    def _rollback(self):  
        """ called pre rollback of the DB.
            interested subclasses may override """
        for action in self.rbactions:
            action()
        self.rbactions = []
        self.uncommitted = {}
        self.idcache = {}
    def _clear(self):
        view = self.getview(1)
        if len(view):
            view[:] = []
            self.db.dirty = 1
        iv = self.getindexview(1)
        if iv:
            iv[:] = []
    def rollbackaction(self, action):
        """ call this to register a callback called on rollback
            callback is removed on end of transaction """
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
            return view.ordered(1)
        # need to create or restructure the mk view
        # id comes first, so MK will order it for us
        self.db.dirty = 1
        s = ["%s[id:I" % self.classname]
        for nm, rutyp in self.ruprops.items():
            mktyp = _typmap[rutyp.__class__]
            s.append('%s:%s' % (nm, mktyp))
            if mktyp == 'V':
                s[-1] += ('[fid:I]')
        s.append('_isdel:I,activity:I,creation:I,creator:I]')
        v = self.db._db.getas(','.join(s))
        self.db.commit()
        return v.ordered(1)
    def getview(self, RW=0):
        return self.db._db.view(self.classname).ordered(1)
    def getindexview(self, RW=0):
        return self.db._db.view("_%s" % self.classname).ordered(1)

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

_converters = {
    hyperdb.Date   : _fetchDate,
    hyperdb.Link   : _fetchLink,
    hyperdb.Multilink : _fetchML,
    hyperdb.Interval  : _fetchInterval,
    hyperdb.Password  : _fetchPW,
    hyperdb.Boolean   : lambda n: n,
    hyperdb.Number    : lambda n: n,
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
    hyperdb.Number    : 'I',
}
class FileClass(Class, hyperdb.FileClass):
    ''' like Class but with a content property
    '''
    default_mime_type = 'text/plain'
    def __init__(self, db, classname, **properties):
        properties['content'] = FileName()
        if not properties.has_key('type'):
            properties['type'] = hyperdb.String()
        Class.__init__(self, db, classname, **properties)

    def get(self, nodeid, propname, default=_marker, cache=1):
        x = Class.get(self, nodeid, propname, default, cache)
        poss_msg = 'Possibly an access right configuration problem.'
        if propname == 'content':
            if x.startswith('file:'):
                fnm = x[5:]
                try:
                    x = open(fnm, 'rb').read()
                except IOError, (strerror):
                    # XXX by catching this we donot see an error in the log.
                    return 'ERROR reading file: %s%s\n%s\n%s'%(
                            self.classname, nodeid, poss_msg, strerror)
        return x

    def create(self, **propvalues):
        self.fireAuditors('create', None, propvalues)
        content = propvalues['content']
        del propvalues['content']
        newid = Class.create_inner(self, **propvalues)
        if not content:
            return newid
        nm = bnm = '%s%s' % (self.classname, newid)
        sd = str(int(int(newid) / 1000))
        d = os.path.join(self.db.config.DATABASE, 'files', self.classname, sd)
        if not os.path.exists(d):
            os.makedirs(d)
        nm = os.path.join(d, nm)
        open(nm, 'wb').write(content)
        self.set(newid, content = 'file:'+nm)
        mimetype = propvalues.get('type', self.default_mime_type)
        self.db.indexer.add_text((self.classname, newid, 'content'), content,
            mimetype)
        def undo(fnm=nm, action1=os.remove, indexer=self.db.indexer):
            action1(fnm)
        self.rollbackaction(undo)
        return newid

    def index(self, nodeid):
        Class.index(self, nodeid)
        mimetype = self.get(nodeid, 'type')
        if not mimetype:
            mimetype = self.default_mime_type
        self.db.indexer.add_text((self.classname, nodeid, 'content'),
                    self.get(nodeid, 'content'), mimetype)
 
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

class Indexer(indexer.Indexer):
    disallows = {'THE':1, 'THIS':1, 'ZZZ':1, 'THAT':1, 'WITH':1}
    def __init__(self, path, datadb):
        self.path = os.path.join(path, 'index.mk4')
        self.db = metakit.storage(self.path, 1)
        self.datadb = datadb
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

    def force_reindex(self):
        v = self.db.view('ids')
        v[:] = []
        v = self.db.view('index')
        v[:] = []
        self.db.commit()
        self.reindex = 1

    def should_reindex(self):
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
	    if not self.disallows.has_key(word):
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
            return {}
        rslt = {}
        ids = self.db.view('ids').remapwith(hits)
        tbls = self.datadb.view('tables')
        for i in range(len(ids)):
            hit = ids[i]
            if not hit.ignore:
                classname = tbls[hit.tblid].name
                nodeid = str(hit.nodeid)
                property = self._getpropname(classname, hit.propid)
                rslt[i] = (classname, nodeid, property)
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

