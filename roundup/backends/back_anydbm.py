#$Id: back_anydbm.py,v 1.1 2001-07-23 07:22:13 richard Exp $

import anydbm, os, cPickle
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
            anydbm.open(db, 'n')
            db = os.path.join(self.dir, 'journals.%s'%cn)
            anydbm.open(db, 'n')

    def getclassdb(self, classname, mode='r'):
        ''' grab a connection to the class db that will be used for
            multiple actions
        '''
        path = os.path.join(os.getcwd(), self.dir, 'nodes.%s'%classname)
        return anydbm.open(path, mode)

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
        db = anydbm.open(os.path.join(self.dir, 'journals.%s'%classname), 'c')
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
        db = anydbm.open(os.path.join(self.dir, 'journals.%s'%classname), 'r')
        res = cPickle.loads(db[nodeid])
        db.close()
        return res

    def close(self):
        ''' Close the Database - we must release the circular refs so that
            we can be del'ed and the underlying anydbm connections closed
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
#Revision 1.1  2001/07/23 07:15:57  richard
#Moved the backends into the backends package. Anydbm hasn't been tested at all.
#
#
