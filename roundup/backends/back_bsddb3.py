#$Id: back_bsddb3.py,v 1.2 2001-07-30 01:41:36 richard Exp $

import bsddb3, os, marshal
from roundup import hyperdb, date

#
# Now the database
#
class Database(hyperdb.Database):
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
            bsddb3.btopen(db, 'n')
            db = os.path.join(self.dir, 'journals.%s'%cn)
            bsddb3.btopen(db, 'n')

    def getclassdb(self, classname, mode='r'):
        ''' grab a connection to the class db that will be used for
            multiple actions
        '''
        path = os.path.join(os.getcwd(), self.dir, 'nodes.%s'%classname)
        return bsddb3.btopen(path, mode)

    #
    # Nodes
    #
    def addnode(self, classname, nodeid, node):
        ''' add the specified node to its class's db
        '''
        db = self.getclassdb(classname, 'c')

        # convert the instance data to builtin types
        properties = self.classes[classname].properties
        for key in properties.keys():
            if properties[key].isDateType:
                node[key] = node[key].get_tuple()
            elif properties[key].isIntervalType:
                node[key] = node[key].get_tuple()

        # now save the marshalled data
        db[nodeid] = marshal.dumps(node)
        db.close()
    setnode = addnode

    def getnode(self, classname, nodeid, cldb=None):
        ''' add the specified node to its class's db
        '''
        db = cldb or self.getclassdb(classname)
        if not db.has_key(nodeid):
            raise IndexError, nodeid
        res = marshal.loads(db[nodeid])

        # convert the marshalled data to instances
        properties = self.classes[classname].properties
        for key in properties.keys():
            if properties[key].isDateType:
                res[key] = date.Date(res[key])
            elif properties[key].isIntervalType:
                res[key] = date.Interval(res[key])

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
        entry = (nodeid, date.Date().get_tuple(), self.journaltag, action,
            params)
        db = bsddb3.btopen(os.path.join(self.dir, 'journals.%s'%classname), 'c')
        if db.has_key(nodeid):
            s = db[nodeid]
            l = marshal.loads(db[nodeid])
            l.append(entry)
        else:
            l = [entry]
        db[nodeid] = marshal.dumps(l)
        db.close()

    def getjournal(self, classname, nodeid):
        ''' get the journal for id
        '''
        # attempt to open the journal - in some rare cases, the journal may
        # not exist
        try:
            db = bsddb3.btopen(os.path.join(self.dir, 'journals.%s'%classname),
                'r')
        except bsddb3.error, error:
            if error.args[0] != 2: raise
            return []
        # mor handling of bad journals
        if not db.has_key(nodeid): return []
        journal = marshal.loads(db[nodeid])
        res = []
        for entry in journal:
            (nodeid, date_stamp, self.journaltag, action, params) = entry
            date_obj = date.Date(date_stamp)
            res.append((nodeid, date_obj, self.journaltag, action, params))
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

#
#$Log: not supported by cvs2svn $
#Revision 1.1  2001/07/24 04:26:03  anthonybaxter
#bsddb3 implementation. For now, it's the bsddb implementation with a "3"
#added in crayon.
#
#Revision 1.4  2001/07/23 08:25:33  richard
#more handling of bad journals
#
#Revision 1.3  2001/07/23 08:20:44  richard
#Moved over to using marshal in the bsddb and anydbm backends.
#roundup-admin now has a "freshen" command that'll load/save all nodes (not
# retired - mod hyperdb.Class.list() so it lists retired nodes)
#
#Revision 1.2  2001/07/23 07:56:05  richard
#Storing only marshallable data in the db - no nasty pickled class references.
#
#Revision 1.1  2001/07/23 07:22:13  richard
#*sigh* some databases have _foo.so as their underlying implementation.
#This time for sure, Rocky.
#
#Revision 1.1  2001/07/23 07:15:57  richard
#Moved the backends into the backends package. Anydbm hasn't been tested at all.
#
#Revision 1.1  2001/07/23 06:23:41  richard
#moved hyper_bsddb.py to the new backends package as bsddb.py
#
#Revision 1.2  2001/07/22 12:09:32  richard
#Final commit of Grande Splite
#
#Revision 1.1  2001/07/22 11:58:35  richard
#More Grande Splite
#
