import weakref, re

from roundup import hyperdb
from roundup.hyperdb import String, Password, Date, Interval, Link, \
    Multilink, DatabaseError, Boolean, Number

class VolatileClass(hyperdb.Class):
    ''' This is a class that just sits in memory, no saving to disk.
        It has no journal.
    '''
    def __init__(self, db, classname, **properties):
        ''' Set up an in-memory store for the nodes of this class
        '''
        self.db = weakref.proxy(db)       # use a weak ref to avoid circularity
        self.classname = classname
        self.properties = properties
        self.id_counter = 1
        self.store = {}
        self.by_key = {}
        self.key = ''
        db.addclass(self)

    def setkey(self, propname):
        prop = self.getprops()[propname]
        if not isinstance(prop, String):
            raise TypeError, 'key properties must be String'
        self.key = propname

    def getprops(self, protected=1):
        d = self.properties.copy()
        if protected:
            d['id'] = String()
        return d

    def create(self, **propvalues):
        ''' Create a new node in the in-memory store
        '''
        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'
        newid = str(self.id_counter)
        self.id_counter += 1

        # get the key value, validate it
        if self.key:
            keyvalue = propvalues[self.key]
            try:
                self.lookup(keyvalue)
            except KeyError:
                pass
            else:
                raise ValueError, 'node with key "%s" exists'%keyvalue
            self.by_key[keyvalue] = newid

        # validate propvalues
        num_re = re.compile('^\d+$')

        for key, value in propvalues.items():

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

            elif isinstance(prop, Multilink):
                if type(value) != type([]):
                    raise TypeError, 'new property "%s" not a list of ids'%key

                # clean up and validate the list of links
                link_class = self.properties[key].classname
                l = []
                for entry in value:
                    if type(entry) != type(''):
                        raise ValueError, '"%s" link value (%s) must be '\
                            'String'%(key, value)
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
        self.store[newid] = propvalues

        return newid

    _marker = []
    def get(self, nodeid, propname, default=_marker, cache=1):
        ''' Get the node from the in-memory store
        '''
        if propname == 'id':
            return nodeid
        return self.store[nodeid][propname]

    def set(self, nodeid, **propvalues):
        ''' Set properties on the node in the in-memory store
        '''
        if not propvalues:
            return

        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'

        node = self.store[nodeid]
        num_re = re.compile('^\d+$')

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
            prop = self.properties[propname]

            # if the value's the same as the existing value, no sense in
            # doing anything
            if node.has_key(propname) and value == node[propname]:
                del propvalues[propname]
                continue

            # do stuff based on the prop type
            if isinstance(prop, Link):
                link_class = self.properties[propname].classname
                # if it isn't a number, it's a key
                if type(value) != type(''):
                    raise ValueError, 'link value must be String'
                if not num_re.match(value):
                    try:
                        value = self.db.classes[link_class].lookup(value)
                    except (TypeError, KeyError):
                        raise IndexError, 'new property "%s": %s not a %s'%(
                            propname, value, self.properties[propname].classname)

                if not self.db.hasnode(link_class, value):
                    raise IndexError, '%s has no node %s'%(link_class, value)

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

        # do the set
        self.store[nodeid] = node

    def lookup(self, keyvalue):
        ''' look up the key node in the store
        '''
        return self.by_key[keyvalue]

    def hasnode(self, nodeid):
        nodeid = str(nodeid)
        return self.store.has_key(nodeid)

    def list(self):
        l = self.store.keys()
        l.sort()
        return l

    def index(self, nodeid):
        pass

