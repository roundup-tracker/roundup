import bsddb, os, cPickle, re, string

import date
#
# Types
#
class BaseType:
    isStringType = 0
    isDateType = 0
    isIntervalType = 0
    isLinkType = 0
    isMultilinkType = 0

class String(BaseType):
    def __init__(self):
        """An object designating a String property."""
        pass
    def __repr__(self):
        return '<%s>'%self.__class__
    isStringType = 1

class Date(BaseType, String):
    isDateType = 1

class Interval(BaseType, String):
    isIntervalType = 1

class Link(BaseType):
    def __init__(self, classname):
        """An object designating a Link property that links to
        nodes in a specified class."""
        self.classname = classname
    def __repr__(self):
        return '<%s to "%s">'%(self.__class__, self.classname)
    isLinkType = 1

class Multilink(BaseType, Link):
    """An object designating a Multilink property that links
       to nodes in a specified class.
    """
    isMultilinkType = 1

class DatabaseError(ValueError):
    pass

#
# Now the database
#
RETIRED_FLAG = '__hyperdb_retired'
class Database:
    """A database for storing records containing flexible data types."""

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
        self.dir, self.journaltag = storagelocator, journaltag
        self.classes = {}

    #
    # Classes
    #
    def __getattr__(self, classname):
        """A convenient way of calling self.getclass(classname)."""
        return self.classes[classname]

    def addclass(self, cl):
        cn = cl.classname
        if self.classes.has_key(cn):
            raise ValueError, cn
        self.classes[cn] = cl

    def getclasses(self):
        """Return a list of the names of all existing classes."""
        l = self.classes.keys()
        l.sort()
        return l

    def getclass(self, classname):
        """Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        """
        return self.classes[classname]

    #
    # Class DBs
    #
    def clear(self):
        for cn in self.classes.keys():
            db = os.path.join(self.dir, 'nodes.%s'%cn)
            bsddb.btopen(db, 'n')
            db = os.path.join(self.dir, 'journals.%s'%cn)
            bsddb.btopen(db, 'n')

    def getclassdb(self, classname, mode='r'):
        ''' grab a connection to the class db that will be used for
            multiple actions
        '''
        path = os.path.join(os.getcwd(), self.dir, 'nodes.%s'%classname)
        return bsddb.btopen(path, mode)

    def addnode(self, classname, nodeid, node):
        ''' add the specified node to its class's db
        '''
        db = self.getclassdb(classname, 'c')
        db[nodeid] = cPickle.dumps(node, 1)
        db.close()
    setnode = addnode

    def getnode(self, classname, nodeid, cldb=None):
        ''' add the specified node to its class's db
        '''
        db = cldb or self.getclassdb(classname)
        if not db.has_key(nodeid):
            raise IndexError, nodeid
        res = cPickle.loads(db[nodeid])
        if not cldb: db.close()
        return res

    def hasnode(self, classname, nodeid, cldb=None):
        ''' add the specified node to its class's db
        '''
        db = cldb or self.getclassdb(classname)
        res = db.has_key(nodeid)
        if not cldb: db.close()
        return res

    def countnodes(self, classname, cldb=None):
        db = cldb or self.getclassdb(classname)
        return len(db.keys())
        if not cldb: db.close()
        return res

    def getnodeids(self, classname, cldb=None):
        db = cldb or self.getclassdb(classname)
        res = db.keys()
        if not cldb: db.close()
        return res

    #
    # Journal
    #
    def addjournal(self, classname, nodeid, action, params):
        ''' Journal the Action
        'action' may be:

            'create' or 'set' -- 'params' is a dictionary of property values
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retire' -- 'params' is None
        '''
        entry = (nodeid, date.Date(), self.journaltag, action, params)
        db = bsddb.btopen(os.path.join(self.dir, 'journals.%s'%classname), 'c')
        if db.has_key(nodeid):
            s = db[nodeid]
            l = cPickle.loads(db[nodeid])
            l.append(entry)
        else:
            l = [entry]
        db[nodeid] = cPickle.dumps(l)
        db.close()

    def getjournal(self, classname, nodeid):
        ''' get the journal for id
        '''
        db = bsddb.btopen(os.path.join(self.dir, 'journals.%s'%classname), 'r')
        res = cPickle.loads(db[nodeid])
        db.close()
        return res

    def close(self):
        ''' Close the Database - we must release the circular refs so that
            we can be del'ed and the underlying bsddb connections closed
            cleanly.
        '''
        self.classes = None


    #
    # Basic transaction support
    #
    # TODO: well, write these methods (and then use them in other code)
    def register_action(self):
        ''' Register an action to the transaction undo log
        '''

    def commit(self):
        ''' Commit the current transaction, start a new one
        '''

    def rollback(self):
        ''' Reverse all actions from the current transaction
        '''


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
        self.db = db
        self.key = ''

        # do the db-related init stuff
        db.addclass(self)

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
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'
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

            prop = self.properties[key]

            if prop.isLinkType:
                value = str(value)
                link_class = self.properties[key].classname
                if not num_re.match(value):
                    try:
                        value = self.db.classes[link_class].lookup(value)
                    except:
                        raise ValueError, 'new property "%s": %s not a %s'%(
                            key, value, self.properties[key].classname)
                propvalues[key] = value
                if not self.db.hasnode(link_class, value):
                    raise ValueError, '%s has no node %s'%(link_class, value)

                # register the link with the newly linked node
                self.db.addjournal(link_class, value, 'link',
                    (self.classname, newid, key))

            elif prop.isMultilinkType:
                if type(value) != type([]):
                    raise TypeError, 'new property "%s" not a list of ids'%key
                link_class = self.properties[key].classname
                l = []
                for entry in map(str, value):
                    if not num_re.match(entry):
                        try:
                            entry = self.db.classes[link_class].lookup(entry)
                        except:
                            raise ValueError, 'new property "%s": %s not a %s'%(
                                key, entry, self.properties[key].classname)
                    l.append(entry)
                value = l
                propvalues[key] = value

                # handle additions
                for id in value:
                    if not self.db.hasnode(link_class, id):
                        raise ValueError, '%s has no node %s'%(link_class, id)
                    # register the link with the newly linked node
                    self.db.addjournal(link_class, id, 'link',
                        (self.classname, newid, key))

            elif prop.isStringType:
                if type(value) != type(''):
                    raise TypeError, 'new property "%s" not a string'%key

            elif prop.isDateType:
                if not hasattr(value, 'isDate'):
                    raise TypeError, 'new property "%s" not a Date'% key

            elif prop.isIntervalType:
                if not hasattr(value, 'isInterval'):
                    raise TypeError, 'new property "%s" not an Interval'% key

        for key,prop in self.properties.items():
            if propvalues.has_key(str(key)):
                continue
            if prop.isMultilinkType:
                propvalues[key] = []
            else:
                propvalues[key] = None

        # done
        self.db.addnode(self.classname, newid, propvalues)
        self.db.addjournal(self.classname, newid, 'create', propvalues)
        return newid

    def get(self, nodeid, propname):
        """Get the value of a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.  'propname' must be the name of a property
        of this class or a KeyError is raised.
        """
        d = self.db.getnode(self.classname, str(nodeid))
        return d[propname]

    # XXX not in spec
    def getnode(self, nodeid):
        ''' Return a convenience wrapper for the node
        '''
        return Node(self, nodeid)

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
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'
        nodeid = str(nodeid)
        node = self.db.getnode(self.classname, nodeid)
        if node.has_key(RETIRED_FLAG):
            raise IndexError
        num_re = re.compile('^\d+$')
        for key, value in propvalues.items():
            if not node.has_key(key):
                raise KeyError, key

            if key == self.key:
                try:
                    self.lookup(value)
                except KeyError:
                    pass
                else:
                    raise ValueError, 'node with key "%s" exists'%value

            prop = self.properties[key]

            if prop.isLinkType:
                value = str(value)
                link_class = self.properties[key].classname
                if not num_re.match(value):
                    try:
                        value = self.db.classes[link_class].lookup(value)
                    except:
                        raise ValueError, 'new property "%s": %s not a %s'%(
                            key, value, self.properties[key].classname)

                if not self.db.hasnode(link_class, value):
                    raise ValueError, '%s has no node %s'%(link_class, value)

                # register the unlink with the old linked node
                if node[key] is not None:
                    self.db.addjournal(link_class, node[key], 'unlink',
                        (self.classname, nodeid, key))

                # register the link with the newly linked node
                if value is not None:
                    self.db.addjournal(link_class, value, 'link',
                        (self.classname, nodeid, key))

            elif prop.isMultilinkType:
                if type(value) != type([]):
                    raise TypeError, 'new property "%s" not a list of ids'%key
                link_class = self.properties[key].classname
                l = []
                for entry in map(str, value):
                    if not num_re.match(entry):
                        try:
                            entry = self.db.classes[link_class].lookup(entry)
                        except:
                            raise ValueError, 'new property "%s": %s not a %s'%(
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
                        raise ValueError, '%s has no node %s'%(link_class, id)
                    if id in l:
                        continue
                    # register the link with the newly linked node
                    self.db.addjournal(link_class, id, 'link',
                        (self.classname, nodeid, key))
                    l.append(id)

            elif prop.isStringType:
                if value is not None and type(value) != type(''):
                    raise TypeError, 'new property "%s" not a string'%key

            elif prop.isDateType:
                if not hasattr(value, 'isDate'):
                    raise TypeError, 'new property "%s" not a Date'% key

            elif prop.isIntervalType:
                if not hasattr(value, 'isInterval'):
                    raise TypeError, 'new property "%s" not an Interval'% key

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
        nodeid = str(nodeid)
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'
        node = self.db.getnode(self.classname, nodeid)
        node[RETIRED_FLAG] = 1
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
        cldb = self.db.getclassdb(self.classname)
        for nodeid in self.db.getnodeids(self.classname, cldb):
            node = self.db.getnode(self.classname, nodeid, cldb)
            if node.has_key(RETIRED_FLAG):
                continue
            if node[self.key] == keyvalue:
                return nodeid
        cldb.close()
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
            nodeid = str(nodeid)
            # check the prop is OK
            prop = self.properties[propname]
            if not prop.isLinkType and not prop.isMultilinkType:
                raise TypeError, "'%s' not a Link/Multilink property"%propname
            if not self.db.hasnode(prop.classname, nodeid):
                raise ValueError, '%s has no node %s'%(link_class, nodeid)

        # ok, now do the find
        cldb = self.db.getclassdb(self.classname)
        l = []
        for id in self.db.getnodeids(self.classname, cldb):
            node = self.db.getnode(self.classname, id, cldb)
            if node.has_key(RETIRED_FLAG):
                continue
            for propname, nodeid in propspec:
                nodeid = str(nodeid)
                property = node[propname]
                if prop.isLinkType and nodeid == property:
                    l.append(id)
                elif prop.isMultilinkType and nodeid in property:
                    l.append(id)
        cldb.close()
        return l

    def stringFind(self, **requirements):
        """Locate a particular node by matching a set of its String properties.

        If the property is not a String property, a TypeError is raised.
        
        The return is a list of the id of all nodes that match.
        """
        for propname in requirements.keys():
            prop = self.properties[propname]
            if not prop.isStringType:
                raise TypeError, "'%s' not a String property"%propname
        l = []
        cldb = self.db.getclassdb(self.classname)
        for nodeid in self.db.getnodeids(self.classname, cldb):
            node = self.db.getnode(self.classname, nodeid, cldb)
            if node.has_key(RETIRED_FLAG):
                continue
            for key, value in requirements.items():
                if node[key] != value:
                    break
            else:
                l.append(nodeid)
        cldb.close()
        return l

    def list(self):
        """Return a list of the ids of the active nodes in this class."""
        l = []
        cn = self.classname
        cldb = self.db.getclassdb(cn)
        for nodeid in self.db.getnodeids(cn, cldb):
            node = self.db.getnode(cn, nodeid, cldb)
            if node.has_key(RETIRED_FLAG):
                continue
            l.append(nodeid)
        l.sort()
        cldb.close()
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
            if propclass.isLinkType:
                if type(v) is not type([]):
                    v = [v]
                # replace key values with node ids
                u = []
                link_class =  self.db.classes[propclass.classname]
                for entry in v:
                    if not num_re.match(entry):
                        try:
                            entry = link_class.lookup(entry)
                        except:
                            raise ValueError, 'new property "%s": %s not a %s'%(
                                key, entry, self.properties[key].classname)
                    u.append(entry)

                l.append((0, k, u))
            elif propclass.isMultilinkType:
                if type(v) is not type([]):
                    v = [v]
                # replace key values with node ids
                u = []
                link_class =  self.db.classes[propclass.classname]
                for entry in v:
                    if not num_re.match(entry):
                        try:
                            entry = link_class.lookup(entry)
                        except:
                            raise ValueError, 'new property "%s": %s not a %s'%(
                                key, entry, self.properties[key].classname)
                    u.append(entry)
                l.append((1, k, u))
            elif propclass.isStringType:
                v = v[0]
                if '*' in v or '?' in v:
                    # simple glob searching
                    v = v.replace('?', '.')
                    v = v.replace('*', '.*?')
                    v = re.compile(v)
                    l.append((2, k, v))
                elif v[0] == '^':
                    # start-anchored
                    if v[-1] == '$':
                        # _and_ end-anchored
                        l.append((6, k, v[1:-1]))
                    l.append((3, k, v[1:]))
                elif v[-1] == '$':
                    # end-anchored
                    l.append((4, k, v[:-1]))
                else:
                    # substring
                    l.append((5, k, v))
            else:
                l.append((6, k, v))
        filterspec = l

        # now, find all the nodes that are active and pass filtering
        l = []
        cldb = self.db.getclassdb(cn)
        for nodeid in self.db.getnodeids(cn, cldb):
            node = self.db.getnode(cn, nodeid, cldb)
            if node.has_key(RETIRED_FLAG):
                continue
            # apply filter
            for t, k, v in filterspec:
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
                elif t == 3 and node[k][:len(v)] != v:
                    # start anchored
                    break
                elif t == 4 and node[k][-len(v):] != v:
                    # end anchored
                    break
                elif t == 5 and node[k].find(v) == -1:
                    # substring search
                    break
                elif t == 6 and node[k] != v:
                    # straight value comparison for the other types
                    break
            else:
                l.append((nodeid, node))
        l.sort()
        cldb.close()

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
            for list in group, sort:
                for dir, prop in list:
                    # handle the properties that might be "faked"
                    if not an.has_key(prop):
                        an[prop] = cl.get(a_id, prop)
                    av = an[prop]
                    if not bn.has_key(prop):
                        bn[prop] = cl.get(b_id, prop)
                    bv = bn[prop]

                    # sorting is class-specific
                    propclass = properties[prop]

                    # String and Date values are sorted in the natural way
                    if propclass.isStringType:
                        # clean up the strings
                        if av and av[0] in string.uppercase:
                            av = an[prop] = av.lower()
                        if bv and bv[0] in string.uppercase:
                            bv = bn[prop] = bv.lower()
                    if propclass.isStringType or propclass.isDateType:
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
                    elif propclass.isLinkType:
                        link = db.classes[propclass.classname]
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
                    elif propclass.isMultilinkType:
                        if dir == '+':
                            r = cmp(len(av), len(bv))
                            if r != 0: return r
                        elif dir == '-':
                            r = cmp(len(bv), len(av))
                            if r != 0: return r
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

    def getprops(self):
        """Return a dictionary mapping property names to property objects."""
        return self.properties

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
    def __init__(self, cl, nodeid):
        self.__dict__['cl'] = cl
        self.__dict__['nodeid'] = nodeid
    def keys(self):
        return self.cl.getprops().keys()
    def has_key(self, name):
        return self.cl.getprops().has_key(name)
    def __getattr__(self, name):
        if self.__dict__.has_key(name):
            return self.__dict__['name']
        try:
            return self.cl.get(self.nodeid, name)
        except KeyError, value:
            raise AttributeError, str(value)
    def __getitem__(self, name):
        return self.cl.get(self.nodeid, name)
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


if __name__ == '__main__':
    import pprint
    db = Database("test_db", "richard")
    status = Class(db, "status", name=String())
    status.setkey("name")
    print db.status.create(name="unread")
    print db.status.create(name="in-progress")
    print db.status.create(name="testing")
    print db.status.create(name="resolved")
    print db.status.count()
    print db.status.list()
    print db.status.lookup("in-progress")
    db.status.retire(3)
    print db.status.list()
    issue = Class(db, "issue", title=String(), status=Link("status"))
    db.issue.create(title="spam", status=1)
    db.issue.create(title="eggs", status=2)
    db.issue.create(title="ham", status=4)
    db.issue.create(title="arguments", status=2)
    db.issue.create(title="abuse", status=1)
    user = Class(db, "user", username=String(), password=String())
    user.setkey("username")
    db.issue.addprop(fixer=Link("user"))
    print db.issue.getprops()
#{"title": <hyperdb.String>, "status": <hyperdb.Link to "status">,
#"user": <hyperdb.Link to "user">}
    db.issue.set(5, status=2)
    print db.issue.get(5, "status")
    print db.status.get(2, "name")
    print db.issue.get(5, "title")
    print db.issue.find(status = db.status.lookup("in-progress"))
    print db.issue.history(5)
# [(<Date 2000-06-28.19:09:43>, "ping", "create", {"title": "abuse", "status": 1}),
# (<Date 2000-06-28.19:11:04>, "ping", "set", {"status": 2})]
    print db.status.history(1)
# [(<Date 2000-06-28.19:09:43>, "ping", "link", ("issue", 5, "status")),
# (<Date 2000-06-28.19:11:04>, "ping", "unlink", ("issue", 5, "status"))]
    print db.status.history(2)
# [(<Date 2000-06-28.19:11:04>, "ping", "link", ("issue", 5, "status"))]

    # TODO: set up some filter tests

