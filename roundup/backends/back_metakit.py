from roundup import hyperdb, date, password, roundupdb
import metakit
import re, marshal, os, sys, weakref, time, calendar
from roundup.indexer import Indexer

_instances = weakref.WeakValueDictionary()

def Database(config, journaltag=None):
    if _instances.has_key(id(config)):
        db = _instances[id(config)]
        old = db.journaltag
        db.journaltag = journaltag
        try:
            delattr(db, 'curuserid')
        except AttributeError:
            pass
        return db
    else:
        db = _Database(config, journaltag)
        _instances[id(config)] = db
        return db

class _Database(hyperdb.Database):
    def __init__(self, config, journaltag=None):
        self.config = config
        self.journaltag = journaltag
        self.classes = {}
        self._classes = []
        self.dirty = 0
        self.__RW = 0
        self._db = self.__open()
        self.indexer = Indexer(self.config.DATABASE)
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
            try:
                self.curuserid = x = int(self.classes['user'].lookup(self.journaltag))
            except KeyError:
                x = 0
            return x
        return self.getclass(classname)
    def getclass(self, classname):
        return self.classes[classname]
    def getclasses(self):
        return self.classes.keys()
    # --- end of ping's spec 
    # --- exposed methods
    def commit(self):
        if self.dirty:
            if self.__RW:
                self._db.commit()
                for cl in self.classes.values():
                    cl._commit()
                self.indexer.save_index()
            else:
                raise RuntimeError, "metakit is open RO"
        self.dirty = 0
    def rollback(self):
        if self.dirty:
            for cl in self.classes.values():
                cl._rollback()
            self._db.rollback()
        self.dirty = 0
    def clear(self):
        for cl in self.classes.values():
            cl._clear()
    def hasnode(self, classname, nodeid):
        return self.getclass(clasname).hasnode(nodeid)
    def pack(self, pack_before):
        pass
    def addclass(self, cl):
        self.classes[cl.classname] = cl
    def addjournal(self, tablenm, nodeid, action, params):
        tblid = self.tables.find(name=tablenm)
        if tblid == -1:
            tblid = self.tables.append(name=tablenm)
        # tableid:I,nodeid:I,date:I,user:I,action:I,params:B
        self.hist.append(tableid=tblid,
                         nodeid=int(nodeid),
                         date=int(time.time()),
                         action=action,
                         user = self.curuserid,
                         params = marshal.dumps(params))
    def gethistory(self, tablenm, nodeid):
        rslt = []
        tblid = self.tables.find(name=tablenm)
        if tblid == -1:
            return rslt
        q = self.hist.select(tableid=tblid, nodeid=int(nodeid))
        i = 0
        userclass = self.getclass('user')
        for row in q:
            try:
                params = marshal.loads(row.params)
            except ValueError:
                print "history couldn't unmarshal %r" % row.params
                params = {}
            usernm = userclass.get(str(row.user), 'username')
            dt = date.Date(time.gmtime(row.date))
            rslt.append((i, dt, usernm, _actionnames[row.action], params))
            i += 1
        return rslt
            
    def close(self):
        import time
        now = time.time
        start = now()
        for cl in self.classes.values():
            cl.db = None
        #self._db.rollback()
        #print "pre-close cleanup of DB(%d) took %2.2f secs" % (self.__RW, now()-start)
        self._db = None
        #print "close of DB(%d) took %2.2f secs" % (self.__RW, now()-start)
        self.classes = {}
        try:
            del _instances[id(self.config)]
        except KeyError:
            pass
        self.__RW = 0
        
    # --- internal
    def __open(self):
        self.dbnm = db = os.path.join(self.config.DATABASE, 'tracker.mk4')
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
        else:
            self.__RW = 1
        if not self.fastopen:
            self.__RW = 1
        db = metakit.storage(db, self.__RW)
        hist = db.view('history')
        tables = db.view('tables')
        if not self.fastopen:
            if not hist.structure():
                hist = db.getas('history[tableid:I,nodeid:I,date:I,user:I,action:I,params:B]')
            if not tables.structure():
                tables = db.getas('tables[name:S]')
        self.tables = tables
        self.hist = hist
        return db
    def isReadOnly(self):
        return self.__RW == 0
    def getWriteAccess(self):
        if self.journaltag is not None and self.__RW == 0:
            now = time.time
            start = now()
            self._db = None
            #print "closing the file took %2.2f secs" % (now()-start)
            start = now()
            self._db = metakit.storage(self.dbnm, 1)
            self.__RW = 1
            self.hist = self._db.view('history')
            self.tables = self._db.view('tables')
            #print "getting RW access took %2.2f secs" % (now()-start)
    
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

class Class:    # no, I'm not going to subclass the existing!
    privateprops = None
    def __init__(self, db, classname, **properties):
        self.db = weakref.proxy(db)
        self.classname = classname
        self.keyname = None
        self.ruprops = properties
        self.privateprops = { 'id' : hyperdb.String(),
                              'activity' : hyperdb.Date(),
                              'creation' : hyperdb.Date(),
                              'creator'  : hyperdb.Link('user') }
        self.auditors = {'create': [], 'set': [], 'retire': []} # event -> list of callables
        self.reactors = {'create': [], 'set': [], 'retire': []} # ditto
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
        if not propvalues:
            return
        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'
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
                # if it isn't a number, it's a key
                if type(value) != _STRINGTYPE:
                    raise ValueError, 'link value must be String'
                try:
                    int(value)
                except ValueError:
                    try:
                        value = self.db.getclass(link_class).lookup(value)
                    except (TypeError, KeyError):
                        raise IndexError, 'new property "%s": %s not a %s'%(
                            key, value, prop.classname)

                if not self.db.getclass(link_class).hasnode(value):
                    raise IndexError, '%s has no node %s'%(link_class, value)

                setattr(row, key, int(value))
                changes[key] = oldvalue
                
                if self.do_journal and prop.do_journal:
                    # register the unlink with the old linked node
                    if oldvalue:
                        self.db.addjournal(link_class, value, _UNLINK, (self.classname, str(row.id), key))

                    # register the link with the newly linked node
                    if value:
                        self.db.addjournal(link_class, value, _LINK, (self.classname, str(row.id), key))

            elif isinstance(prop, hyperdb.Multilink):
                if type(value) != _LISTTYPE:
                    raise TypeError, 'new property "%s" not a list of ids'%key
                link_class = prop.classname
                l = []
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
                            self.db.addjournal(link_class, id, _UNLINK, (self.classname, str(row.id), key))

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
                            self.db.addjournal(link_class, id, _LINK, (self.classname, str(row.id), key))
                            
                sv = getattr(row, key)
                i = 0
                while i < len(sv):
                    if str(sv[i].fid) in rmvd:
                        sv.delete(i)
                    else:
                        i += 1
                for id in adds:
                    sv.append(fid=int(id))
                changes[key] = oldvalue
                    

            elif isinstance(prop, hyperdb.String):
                if value is not None and type(value) != _STRINGTYPE:
                    raise TypeError, 'new property "%s" not a string'%key
                setattr(row, key, value)
                changes[key] = oldvalue
                if hasattr(prop, 'isfilename') and prop.isfilename:
                    propvalues[key] = os.path.basename(value)
                if prop.indexme:
                    self.db.indexer.add_text((self.classname, nodeid, key), value, 'text/plain')

            elif isinstance(prop, hyperdb.Password):
                if not isinstance(value, password.Password):
                    raise TypeError, 'new property "%s" not a Password'% key
                setattr(row, key, str(value))
                changes[key] = str(oldvalue)
                propvalues[key] = str(value)

            elif value is not None and isinstance(prop, hyperdb.Date):
                if not isinstance(value, date.Date):
                    raise TypeError, 'new property "%s" not a Date'% key
                setattr(row, key, int(calendar.timegm(value.get_tuple())))
                changes[key] = str(oldvalue)
                propvalues[key] = str(value)

            elif value is not None and isinstance(prop, hyperdb.Interval):
                if not isinstance(value, date.Interval):
                    raise TypeError, 'new property "%s" not an Interval'% key
                setattr(row, key, str(value))
                changes[key] = str(oldvalue)
                propvalues[key] = str(value)

            oldnode[key] = oldvalue

        # nothing to do?
        if not propvalues:
            return
        if not row.activity:
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
            else:
                self.db.addjournal(self.classname, nodeid, _SET, changes)

    def retire(self, nodeid):
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
        iv = self.getindexview(1)
        ndx = iv.find(k=getattr(row, self.keyname),i=row.id)
        if ndx > -1:
            iv.delete(ndx)
        self.db.dirty = 1
    def history(self, nodeid):
        if not self.do_journal:
            raise ValueError, 'Journalling is disabled for this class'
        return self.db.gethistory(self.classname, nodeid)
    def setkey(self, propname):
        if self.keyname:
            if propname == self.keyname:
                return
            raise ValueError, "%s already indexed on %s" % (self.classname, self.keyname)
        # first setkey for this run
        self.keyname = propname
        iv = self.db._db.view('_%s' % self.classname)
        if self.db.fastopen or iv.structure():
            return
        # very first setkey ever
        iv = self.db._db.getas('_%s[k:S,i:I]' % self.classname)
        iv = iv.ordered(1)
        #XXX
#        print "setkey building index"
        for row in self.getview():
            iv.append(k=getattr(row, propname), i=row.id)
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
                ids = {ids:1}
            prop = self.ruprops[propname]
            view = self.getview()
            if isinstance(prop, hyperdb.Multilink):
                view = view.flatten(getattr(view, propname))
                def ff(row, nm=propname, ids=ids):
                    return ids.has_key(str(row.fid))
            else:
                def ff(row, nm=propname, ids=ids):
                    return ids.has_key(str(getattr(row, nm)))
            ndxview = view.filter(ff)
            vws.append(ndxview.unique())

        # handle the empty match case
        if not vws:
            return []

        ndxview = vws[0]
        for v in vws[1:]:
            ndxview = ndxview.union(v)
        view = view.remapwith(ndxview)
        rslt = []
        for row in view:
            rslt.append(str(row.id))
        return rslt
            

    def list(self):
        l = []
        for row in self.getview().select(_isdel=0):
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
                raise ValueError, "%s is already a property of %s" % (key, self.classname)
        self.ruprops.update(properties)
        view = self.__getview()
    # ---- end of ping's spec
    def filter(self, search_matches, filterspec, sort, group):
        # search_matches is None or a set (dict of {nodeid: {propname:[nodeid,...]}})
        # filterspec is a dict {propname:value}
        # sort and group are lists of propnames
        
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
            else:
                where[propname] = str(value)
        v = self.getview()
        #print "filter start at  %s" % time.time() 
        if where:
            v = v.select(where)
        #print "filter where at  %s" % time.time() 
            
        if mlcriteria:
                    # multilink - if any of the nodeids required by the
                    # filterspec aren't in this node's property, then skip
                    # it
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
                    val = getattr(row, propname)
                    if not regex.search(val):
                        return 0
                return 1
            
            iv = v.filter(ff)
            v = v.remapwith(iv)
        #print "filter regexs at %s" % time.time() 
        
        if sort or group:
            sortspec = []
            rev = []
            for propname in group + sort:
                isreversed = 0
                if propname[0] == '-':
                    propname = propname[1:]
                    isreversed = 1
                try:
                    prop = getattr(v, propname)
                except AttributeError:
                    # I can't sort on 'activity', cause it's psuedo!!
                    continue
                if isreversed:
                    rev.append(prop)
                sortspec.append(prop)
            v = v.sortrev(sortspec, rev)[:] #XXX Aaaabh
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
        db = self.db._db
        view = db.view(self.classname)
        if self.db.fastopen:
            return view.ordered(1)
        # is the definition the same?
        mkprops = view.structure()
        for nm, rutyp in self.ruprops.items():
            for mkprop in mkprops:
                if mkprop.name == nm:
                    break
            else:
                mkprop = None
            if mkprop is None:
                #print "%s missing prop %s (%s)" % (self.classname, nm, rutyp.__class__.__name__)
                break
            if _typmap[rutyp.__class__] != mkprop.type:
                #print "%s - prop %s (%s) has wrong mktyp (%s)" % (self.classname, nm, rutyp.__class__.__name__, mkprop.type)
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
        v = db.getas(','.join(s))
        return v.ordered(1)
    def getview(self, RW=0):
        if RW and self.db.isReadOnly():
            self.db.getWriteAccess()
        return self.db._db.view(self.classname).ordered(1)
    def getindexview(self, RW=0):
        if RW and self.db.isReadOnly():
            self.db.getWriteAccess()
        return self.db._db.view("_%s" % self.classname).ordered(1)
    
def _fetchML(sv):
    l = []
    for row in sv:
        if row.fid:
            l.append(str(row.fid))
    return l

def _fetchPW(s):
    p = password.Password()
    p.unpack(s)
    return p

def _fetchLink(n):
    return n and str(n) or None

def _fetchDate(n):
    return date.Date(time.gmtime(n))

_converters = {
    hyperdb.Date   : _fetchDate,
    hyperdb.Link   : _fetchLink,
    hyperdb.Multilink : _fetchML,
    hyperdb.Interval  : date.Interval,
    hyperdb.Password  : _fetchPW,
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
}
class FileClass(Class):
    ' like Class but with a content property '
    default_mime_type = 'text/plain'
    def __init__(self, db, classname, **properties):
        properties['content'] = FileName()
        if not properties.has_key('type'):
            properties['type'] = hyperdb.String()
        Class.__init__(self, db, classname, **properties)
    def get(self, nodeid, propname, default=_marker, cache=1):
        x = Class.get(self, nodeid, propname, default, cache)
        if propname == 'content':
            if x.startswith('file:'):
                fnm = x[5:]
                try:
                    x = open(fnm, 'rb').read()
                except Exception, e:
                    x = repr(e)
        return x
    def create(self, **propvalues):
        content = propvalues['content']
        del propvalues['content']
        newid = Class.create(self, **propvalues)
        if not content:
            return newid
        if content.startswith('/tracker/download.php?'):
            self.set(newid, content='http://sourceforge.net'+content)
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
        self.db.indexer.add_text((self.classname, newid, 'content'), content, mimetype)
        def undo(fnm=nm, action1=os.remove, indexer=self.db.indexer):
            remove(fnm)
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
    # Overridden methods:
    def __init__(self, db, classname, **properties):
        """The newly-created class automatically includes the "messages",
        "files", "nosy", and "superseder" properties.  If the 'properties'
        dictionary attempts to specify any of these properties or a
        "creation" or "activity" property, a ValueError is raised."""
        if not properties.has_key('title'):
            properties['title'] = hyperdb.String(indexme='yes')
        if not properties.has_key('messages'):
            properties['messages'] = hyperdb.Multilink("msg")
        if not properties.has_key('files'):
            properties['files'] = hyperdb.Multilink("file")
        if not properties.has_key('nosy'):
            properties['nosy'] = hyperdb.Multilink("user")
        if not properties.has_key('superseder'):
            properties['superseder'] = hyperdb.Multilink(classname)
        Class.__init__(self, db, classname, **properties)

