# $Id: back_gadfly.py,v 1.2 2002-08-23 04:48:10 richard Exp $
__doc__ = '''
About Gadfly
============

Gadfly  is  a  collection  of  python modules that provides relational
database  functionality  entirely implemented in Python. It supports a
subset  of  the intergalactic standard RDBMS Structured Query Language
SQL.


Basic Structure
===============

We map roundup classes to relational tables. Automatically detect schema
changes and modify the gadfly table schemas appropriately. Multilinks
(which represent a many-to-many relationship) are handled through
intermediate tables.

Journals are stored adjunct to the per-class tables.

Table names and columns have "_" prepended so the names can't
clash with restricted names (like "order"). Retirement is determined by the
__retired__ column being true.

All columns are defined as VARCHAR, since it really doesn't matter what
type they're defined as. We stuff all kinds of data in there ;) [as long as
it's marshallable, gadfly doesn't care]


Additional Instance Requirements
================================

The instance configuration must specify where the database is. It does this
with GADFLY_DATABASE, which is used as the arguments to the gadfly.gadfly()
method:

Using an on-disk database directly (not a good idea):
  GADFLY_DATABASE = (database name, directory)

Using a network database (much better idea):
  GADFLY_DATABASE = (policy, password, address, port)

Because multiple accesses directly to a gadfly database aren't handled, but
multiple network accesses are, it's strongly advised that the latter setup be
used.

'''

# standard python modules
import sys, os, time, re, errno, weakref, copy

# roundup modules
from roundup import hyperdb, date, password, roundupdb, security
from roundup.hyperdb import String, Password, Date, Interval, Link, \
    Multilink, DatabaseError, Boolean, Number

# the all-important gadfly :)
import gadfly
import gadfly.client
import gadfly.database

# support
from blobfiles import FileStorage
from roundup.indexer import Indexer
from sessions import Sessions

class Database(FileStorage, hyperdb.Database, roundupdb.Database):
    # flag to set on retired entries
    RETIRED_FLAG = '__hyperdb_retired'

    def __init__(self, config, journaltag=None):
        ''' Open the database and load the schema from it.
        '''
        self.config, self.journaltag = config, journaltag
        self.dir = config.DATABASE
        self.classes = {}
        self.indexer = Indexer(self.dir)
        self.sessions = Sessions(self.config)
        self.security = security.Security(self)

        # additional transaction support for external files and the like
        self.transactions = []

        db = config.GADFLY_DATABASE
        if len(db) == 2:
            # ensure files are group readable and writable
            os.umask(0002)
            try:
                self.conn = gadfly.gadfly(*db)
            except IOError, error:
                if error.errno != errno.ENOENT:
                    raise
                self.database_schema = {}
                self.conn = gadfly.gadfly()
                self.conn.startup(*db)
                cursor = self.conn.cursor()
                cursor.execute('create table schema (schema varchar)')
                cursor.execute('create table ids (name varchar, num integer)')
            else:
                cursor = self.conn.cursor()
                cursor.execute('select schema from schema')
                self.database_schema = cursor.fetchone()[0]
        else:
            self.conn = gadfly.client.gfclient(*db)
            cursor = self.conn.cursor()
            cursor.execute('select schema from schema')
            self.database_schema = cursor.fetchone()[0]

    def __repr__(self):
        return '<radfly 0x%x>'%id(self)

    def post_init(self):
        ''' Called once the schema initialisation has finished.

            We should now confirm that the schema defined by our "classes"
            attribute actually matches the schema in the database.
        '''
        # now detect changes in the schema
        for classname, spec in self.classes.items():
            if self.database_schema.has_key(classname):
                dbspec = self.database_schema[classname]
                self.update_class(spec, dbspec)
                self.database_schema[classname] = spec.schema()
            else:
                self.create_class(spec)
                self.database_schema[classname] = spec.schema()

        for classname in self.database_schema.keys():
            if not self.classes.has_key(classname):
                self.drop_class(classname)

        # update the database version of the schema
        cursor = self.conn.cursor()
        cursor.execute('delete from schema')
        cursor.execute('insert into schema values (?)', (self.database_schema,))

        # reindex the db if necessary
        if self.indexer.should_reindex():
            self.reindex()

        # commit
        self.conn.commit()

    def reindex(self):
        for klass in self.classes.values():
            for nodeid in klass.list():
                klass.index(nodeid)
        self.indexer.save_index()

    def determine_columns(self, spec):
        ''' Figure the column names and multilink properties from the spec
        '''
        cols = []
        mls = []
        # add the multilinks separately
        for col, prop in spec.properties.items():
            if isinstance(prop, Multilink):
                mls.append(col)
            else:
                cols.append('_'+col)
        cols.sort()
        return cols, mls

    def update_class(self, spec, dbspec):
        ''' Determine the differences between the current spec and the
            database version of the spec, and update where necessary

            NOTE that this doesn't work for adding/deleting properties!
             ... until gadfly grows an ALTER TABLE command, it's not going to!
        '''
        spec_schema = spec.schema()
        if spec_schema == dbspec:
            return
        if __debug__:
            print >>hyperdb.DEBUG, 'update_class FIRING'

        # key property changed?
        if dbspec[0] != spec_schema[0]:
            if __debug__:
                print >>hyperdb.DEBUG, 'update_class setting keyprop', `spec[0]`
            # XXX turn on indexing for the key property

        # dict 'em up
        spec_propnames,spec_props = [],{}
        for propname,prop in spec_schema[1]:
            spec_propnames.append(propname)
            spec_props[propname] = prop
        dbspec_propnames,dbspec_props = [],{}
        for propname,prop in dbspec[1]:
            dbspec_propnames.append(propname)
            dbspec_props[propname] = prop

        # we're going to need one of these
        cursor = self.conn.cursor()

        # now compare
        for propname in spec_propnames:
            prop = spec_props[propname]
            if __debug__:
                print >>hyperdb.DEBUG, 'update_class ...', `prop`
            if dbspec_props.has_key(propname) and prop==dbspec_props[propname]:
                continue
            if __debug__:
                print >>hyperdb.DEBUG, 'update_class', `prop`

            if not dbspec_props.has_key(propname):
                # add the property
                if isinstance(prop, Multilink):
                    sql = 'create table %s_%s (linkid varchar, nodeid '\
                        'varchar)'%(spec.classname, prop)
                    if __debug__:
                        print >>hyperdb.DEBUG, 'update_class', (self, sql)
                    cursor.execute(sql)
                else:
                    # XXX gadfly doesn't have an ALTER TABLE command
                    raise NotImplementedError
                    sql = 'alter table _%s add column (_%s varchar)'%(
                        spec.classname, propname)
                    if __debug__:
                        print >>hyperdb.DEBUG, 'update_class', (self, sql)
                    cursor.execute(sql)
            else:
                # modify the property
                if __debug__:
                    print >>hyperdb.DEBUG, 'update_class NOOP'
                pass  # NOOP in gadfly

        # and the other way - only worry about deletions here
        for propname in dbspec_propnames:
            prop = dbspec_props[propname]
            if spec_props.has_key(propname):
                continue
            if __debug__:
                print >>hyperdb.DEBUG, 'update_class', `prop`

            # delete the property
            if isinstance(prop, Multilink):
                sql = 'drop table %s_%s'%(spec.classname, prop)
                if __debug__:
                    print >>hyperdb.DEBUG, 'update_class', (self, sql)
                cursor.execute(sql)
            else:
                # XXX gadfly doesn't have an ALTER TABLE command
                raise NotImplementedError
                sql = 'alter table _%s delete column _%s'%(spec.classname,
                    propname)
                if __debug__:
                    print >>hyperdb.DEBUG, 'update_class', (self, sql)
                cursor.execute(sql)

    def create_class(self, spec):
        ''' Create a database table according to the given spec.
        '''
        cols, mls = self.determine_columns(spec)

        # add on our special columns
        cols.append('id')
        cols.append('__retired__')

        cursor = self.conn.cursor()

        # create the base table
        cols = ','.join(['%s varchar'%x for x in cols])
        sql = 'create table _%s (%s)'%(spec.classname, cols)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)
        cursor.execute(sql)

        # journal table
        cols = ','.join(['%s varchar'%x
            for x in 'nodeid date tag action params'.split()])
        sql = 'create table %s__journal (%s)'%(spec.classname, cols)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)
        cursor.execute(sql)

        # now create the multilink tables
        for ml in mls:
            sql = 'create table %s_%s (linkid varchar, nodeid varchar)'%(
                spec.classname, ml)
            if __debug__:
                print >>hyperdb.DEBUG, 'create_class', (self, sql)
            cursor.execute(sql)

        # ID counter
        sql = 'insert into ids (name, num) values (?,?)'
        vals = (spec.classname, 1)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql, vals)
        cursor.execute(sql, vals)

    def drop_class(self, spec):
        ''' Drop the given table from the database.

            Drop the journal and multilink tables too.
        '''
        # figure the multilinks
        mls = []
        for col, prop in spec.properties.items():
            if isinstance(prop, Multilink):
                mls.append(col)
        cursor = self.conn.cursor()

        sql = 'drop table _%s'%spec.classname
        if __debug__:
            print >>hyperdb.DEBUG, 'drop_class', (self, sql)
        cursor.execute(sql)

        sql = 'drop table %s__journal'%spec.classname
        if __debug__:
            print >>hyperdb.DEBUG, 'drop_class', (self, sql)
        cursor.execute(sql)

        for ml in mls:
            sql = 'drop table %s_%s'%(spec.classname, ml)
            if __debug__:
                print >>hyperdb.DEBUG, 'drop_class', (self, sql)
            cursor.execute(sql)

    #
    # Classes
    #
    def __getattr__(self, classname):
        ''' A convenient way of calling self.getclass(classname).
        '''
        if self.classes.has_key(classname):
            if __debug__:
                print >>hyperdb.DEBUG, '__getattr__', (self, classname)
            return self.classes[classname]
        raise AttributeError, classname

    def addclass(self, cl):
        ''' Add a Class to the hyperdatabase.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'addclass', (self, cl)
        cn = cl.classname
        if self.classes.has_key(cn):
            raise ValueError, cn
        self.classes[cn] = cl

    def getclasses(self):
        ''' Return a list of the names of all existing classes.
        '''
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
        return self.classes[classname]

    def clear(self):
        ''' Delete all database contents.

            Note: I don't commit here, which is different behaviour to the
            "nuke from orbit" behaviour in the *dbms.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'clear', (self,)
        cursor = self.conn.cursor()
        for cn in self.classes.keys():
            sql = 'delete from _%s'%cn
            if __debug__:
                print >>hyperdb.DEBUG, 'clear', (self, sql)
            cursor.execute(sql)

    #
    # Node IDs
    #
    def newid(self, classname):
        ''' Generate a new id for the given class
        '''
        # get the next ID
        cursor = self.conn.cursor()
        sql = 'select num from ids where name=?'
        if __debug__:
            print >>hyperdb.DEBUG, 'newid', (self, sql, classname)
        cursor.execute(sql, (classname, ))
        newid = cursor.fetchone()[0]

        # update the counter
        sql = 'update ids set num=? where name=?'
        vals = (newid+1, classname)
        if __debug__:
            print >>hyperdb.DEBUG, 'newid', (self, sql, vals)
        cursor.execute(sql, vals)

        # return as string
        return str(newid)

    def setid(self, classname, setid):
        ''' Set the id counter: used during import of database
        '''
        cursor = self.conn.cursor()
        sql = 'update ids set num=? where name=?'
        vals = (setid, spec.classname)
        if __debug__:
            print >>hyperdb.DEBUG, 'setid', (self, sql, vals)
        cursor.execute(sql, vals)

    #
    # Nodes
    #

    def addnode(self, classname, nodeid, node):
        ''' Add the specified node to its class's db.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'addnode', (self, classname, nodeid, node)
        # gadfly requires values for all non-multilink columns
        cl = self.classes[classname]
        cols, mls = self.determine_columns(cl)

        # default the non-multilink columns
        for col, prop in cl.properties.items():
            if not isinstance(col, Multilink):
                if not node.has_key(col):
                    node[col] = None

        node = self.serialise(classname, node)

        # make sure the ordering is correct for column name -> column value
        vals = tuple([node[col[1:]] for col in cols]) + (nodeid, 0)
        s = ','.join(['?' for x in cols]) + ',?,?'
        cols = ','.join(cols) + ',id,__retired__'

        # perform the inserts
        cursor = self.conn.cursor()
        sql = 'insert into _%s (%s) values (%s)'%(classname, cols, s)
        if __debug__:
            print >>hyperdb.DEBUG, 'addnode', (self, sql, vals)
        cursor.execute(sql, vals)

        # insert the multilink rows
        for col in mls:
            t = '%s_%s'%(classname, col)
            for entry in node[col]:
                sql = 'insert into %s (linkid, nodeid) values (?,?)'%t
                vals = (entry, nodeid)
                if __debug__:
                    print >>hyperdb.DEBUG, 'addnode', (self, sql, vals)
                cursor.execute(sql, vals)

        # make sure we do the commit-time extra stuff for this node
        self.transactions.append((self.doSaveNode, (classname, nodeid, node)))

    def setnode(self, classname, nodeid, node):
        ''' Change the specified node.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'setnode', (self, classname, nodeid, node)
        node = self.serialise(classname, node)

        cl = self.classes[classname]
        cols = []
        mls = []
        # add the multilinks separately
        for col in node.keys():
            prop = cl.properties[col]
            if isinstance(prop, Multilink):
                mls.append(col)
            else:
                cols.append('_'+col)
        cols.sort()

        # make sure the ordering is correct for column name -> column value
        vals = tuple([node[col[1:]] for col in cols])
        s = ','.join(['%s=?'%x for x in cols])
        cols = ','.join(cols)

        # perform the update
        cursor = self.conn.cursor()
        sql = 'update _%s set %s'%(classname, s)
        if __debug__:
            print >>hyperdb.DEBUG, 'setnode', (self, sql, vals)
        cursor.execute(sql, vals)

        # now the fun bit, updating the multilinks ;)
        # XXX TODO XXX

        # make sure we do the commit-time extra stuff for this node
        self.transactions.append((self.doSaveNode, (classname, nodeid, node)))

    def getnode(self, classname, nodeid):
        ''' Get a node from the database.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'getnode', (self, classname, nodeid)
        # figure the columns we're fetching
        cl = self.classes[classname]
        cols, mls = self.determine_columns(cl)
        scols = ','.join(cols)

        # perform the basic property fetch
        cursor = self.conn.cursor()
        sql = 'select %s from _%s where id=?'%(scols, classname)
        if __debug__:
            print >>hyperdb.DEBUG, 'getnode', (self, sql, nodeid)
        cursor.execute(sql, (nodeid,))
        try:
            values = cursor.fetchone()
        except gadfly.database.error, message:
            if message == 'no more results':
                raise IndexError, 'no such %s node %s'%(classname, nodeid)
            raise

        # make up the node
        node = {}
        for col in range(len(cols)):
            node[cols[col][1:]] = values[col]

        # now the multilinks
        for col in mls:
            # get the link ids
            sql = 'select linkid from %s_%s where nodeid=?'%(classname, col)
            if __debug__:
                print >>hyperdb.DEBUG, 'getnode', (self, sql, nodeid)
            cursor.execute(sql, (nodeid,))
            # extract the first column from the result
            node[col] = [x[0] for x in cursor.fetchall()]

        return self.unserialise(classname, node)

    def destroynode(self, classname, nodeid):
        '''Remove a node from the database. Called exclusively by the
           destroy() method on Class.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'destroynode', (self, classname, nodeid)

        # make sure the node exists
        if not self.hasnode(classname, nodeid):
            raise IndexError, '%s has no node %s'%(classname, nodeid)

        # see if there's any obvious commit actions that we should get rid of
        for entry in self.transactions[:]:
            if entry[1][:2] == (classname, nodeid):
                self.transactions.remove(entry)

        # now do the SQL
        cursor = self.conn.cursor()
        sql = 'delete from _%s where id=?'%(classname)
        if __debug__:
            print >>hyperdb.DEBUG, 'destroynode', (self, sql, nodeid)
        cursor.execute(sql, (nodeid,))

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

            if isinstance(prop, Password):
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
            elif isinstance(prop, Password):
                p = password.Password()
                p.unpack(v)
                d[k] = p
            else:
                d[k] = v
        return d

    def hasnode(self, classname, nodeid):
        ''' Determine if the database has a given node.
        '''
        cursor = self.conn.cursor()
        sql = 'select count(*) from _%s where id=?'%classname
        if __debug__:
            print >>hyperdb.DEBUG, 'hasnode', (self, sql, nodeid)
        cursor.execute(sql, (nodeid,))
        return cursor.fetchone()[0]

    def countnodes(self, classname):
        ''' Count the number of nodes that exist for a particular Class.
        '''
        cursor = self.conn.cursor()
        sql = 'select count(*) from _%s'%classname
        if __debug__:
            print >>hyperdb.DEBUG, 'countnodes', (self, sql)
        cursor.execute(sql)
        return cursor.fetchone()[0]

    def getnodeids(self, classname, retired=0):
        ''' Retrieve all the ids of the nodes for a particular Class.

            Set retired=None to get all nodes. Otherwise it'll get all the 
            retired or non-retired nodes, depending on the flag.
        '''
        cursor = self.conn.cursor()
        # flip the sense of the flag if we don't want all of them
        if retired is not None:
            retired = not retired
        sql = 'select id from _%s where __retired__ <> ?'%classname
        if __debug__:
            print >>hyperdb.DEBUG, 'getnodeids', (self, sql, retired)
        cursor.execute(sql, (retired,))
        return [x[0] for x in cursor.fetchall()]

    def addjournal(self, classname, nodeid, action, params):
        ''' Journal the Action
        'action' may be:

            'create' or 'set' -- 'params' is a dictionary of property values
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retire' -- 'params' is None
        '''
        if isinstance(params, type({})):
            if params.has_key('creator'):
                journaltag = self.user.get(params['creator'], 'username')
                del params['creator']
            else:
                journaltag = self.journaltag
            if params.has_key('created'):
                journaldate = params['created'].serialise()
                del params['created']
            else:
                journaldate = date.Date().serialise()
            if params.has_key('activity'):
                del params['activity']

            # serialise the parameters now
            if action in ('set', 'create'):
                params = self.serialise(classname, params)
        else:
            journaltag = self.journaltag
            journaldate = date.Date().serialise()

        # create the journal entry
        cols = ','.join('nodeid date tag action params'.split())
        entry = (nodeid, journaldate, journaltag, action, params)

        if __debug__:
            print >>hyperdb.DEBUG, 'doSaveJournal', entry

        # do the insert
        cursor = self.conn.cursor()
        sql = 'insert into %s__journal (%s) values (?,?,?,?,?)'%(classname,
            cols)
        if __debug__:
            print >>hyperdb.DEBUG, 'addjournal', (self, sql, entry)
        cursor.execute(sql, entry)

    def getjournal(self, classname, nodeid):
        ''' get the journal for id
        '''
        # make sure the node exists
        if not self.hasnode(classname, nodeid):
            raise IndexError, '%s has no node %s'%(classname, nodeid)

        # now get the journal entries
        cols = ','.join('nodeid date tag action params'.split())
        cursor = self.conn.cursor()
        sql = 'select %s from %s__journal where nodeid=?'%(cols, classname)
        if __debug__:
            print >>hyperdb.DEBUG, 'getjournal', (self, sql, nodeid)
        cursor.execute(sql, (nodeid,))
        res = []
        for nodeid, date_stamp, user, action, params in cursor.fetchall():
            res.append((nodeid, date.Date(date_stamp), user, action, params))
        return res

    def pack(self, pack_before):
        ''' Pack the database, removing all journal entries before the
            "pack_before" date.
        '''
        # get a 'yyyymmddhhmmss' version of the date
        date_stamp = pack_before.serialise()

        # do the delete
        cursor = self.conn.cursor()
        for classname in self.classes.keys():
            sql = 'delete from %s__journal where date<?'%classname
            if __debug__:
                print >>hyperdb.DEBUG, 'pack', (self, sql, date_stamp)
            cursor.execute(sql, (date_stamp,))

    def commit(self):
        ''' Commit the current transactions.

        Save all data changed since the database was opened or since the
        last commit() or rollback().
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'commit', (self,)

        # commit gadfly
        self.conn.commit()

        # now, do all the other transaction stuff
        reindex = {}
        for method, args in self.transactions:
            reindex[method(*args)] = 1

        # reindex the nodes that request it
        for classname, nodeid in filter(None, reindex.keys()):
            print >>hyperdb.DEBUG, 'commit.reindex', (classname, nodeid)
            self.getclass(classname).index(nodeid)

        # save the indexer state
        self.indexer.save_index()

        # clear out the transactions
        self.transactions = []

    def rollback(self):
        ''' Reverse all actions from the current transaction.

        Undo all the changes made since the database was opened or the last
        commit() or rollback() was performed.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'rollback', (self,)

        # roll back gadfly
        self.conn.rollback()

        # roll back "other" transaction stuff
        for method, args in self.transactions:
            # delete temporary files
            if method == self.doStoreFile:
                self.rollbackStoreFile(*args)
        self.transactions = []

    def doSaveNode(self, classname, nodeid, node):
        ''' dummy that just generates a reindex event
        '''
        # return the classname, nodeid so we reindex this content
        return (classname, nodeid)

#
# The base Class class
#
class Class(hyperdb.Class):
    ''' The handle to a particular class of nodes in a hyperdatabase.
        
        All methods except __repr__ and getnode must be implemented by a
        concrete backend Class.
    '''

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

    def schema(self):
        ''' A dumpable version of the schema that we can store in the
            database
        '''
        return (self.key, [(x, repr(y)) for x,y in self.properties.items()])

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
            self.db.addjournal(self.classname, newid, 'create', propvalues)

        self.fireReactors('create', newid, None)

        return newid

    _marker = []
    def get(self, nodeid, propname, default=_marker, cache=1):
        '''Get the value of a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.  'propname' must be the name of a property
        of this class or a KeyError is raised.

        'cache' indicates whether the transaction cache should be queried
        for the node. If the node has been modified and you need to
        determine what its values prior to modification are, you need to
        set cache=0.
        '''
        if propname == 'id':
            return nodeid

        if propname == 'creation':
            if not self.do_journal:
                raise ValueError, 'Journalling is disabled for this class'
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                return self.db.getjournal(self.classname, nodeid)[0][1]
            else:
                # on the strange chance that there's no journal
                return date.Date()
        if propname == 'activity':
            if not self.do_journal:
                raise ValueError, 'Journalling is disabled for this class'
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                return self.db.getjournal(self.classname, nodeid)[-1][1]
            else:
                # on the strange chance that there's no journal
                return date.Date()
        if propname == 'creator':
            if not self.do_journal:
                raise ValueError, 'Journalling is disabled for this class'
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                name = self.db.getjournal(self.classname, nodeid)[0][2]
            else:
                return None
            return self.db.user.lookup(name)

        # get the property (raises KeyErorr if invalid)
        prop = self.properties[propname]

        # get the node's dict
        d = self.db.getnode(self.classname, nodeid) #, cache=cache)

        if not d.has_key(propname):
            if default is self._marker:
                if isinstance(prop, Multilink):
                    return []
                else:
                    return None
            else:
                return default

        return d[propname]

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
        # XXX used to try the cache here first
        oldvalues = copy.deepcopy(self.db.getnode(self.classname, nodeid))

        node = self.db.getnode(self.classname, nodeid)
        if self.is_retired(nodeid):
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
            prop = self.properties[propname]

            # if the value's the same as the existing value, no sense in
            # doing anything
            if node.has_key(propname) and value == node[propname]:
                del propvalues[propname]
                continue

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
                    if node[propname] is not None:
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
            propvalues.update(journalvalues)
            self.db.addjournal(self.classname, nodeid, 'set', propvalues)

        self.fireReactors('set', nodeid, oldvalues)

        return propvalues        

    def retire(self, nodeid):
        '''Retire a node.
        
        The properties on the node remain available from the get() method,
        and the node's id is never reused.
        
        Retired nodes are not returned by the find(), list(), or lookup()
        methods, and other nodes may reuse the values of their key properties.
        '''
        cursor = self.db.conn.cursor()
        sql = 'update _%s set __retired__=1 where id=?'%self.classname
        if __debug__:
            print >>hyperdb.DEBUG, 'retire', (self, sql, nodeid)
        cursor.execute(sql, (nodeid,))

    def is_retired(self, nodeid):
        '''Return true if the node is rerired
        '''
        cursor = self.db.conn.cursor()
        sql = 'select __retired__ from _%s where id=?'%self.classname
        if __debug__:
            print >>hyperdb.DEBUG, 'is_retired', (self, sql, nodeid)
        cursor.execute(sql, (nodeid,))
        return cursor.fetchone()[0]

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

        The node is completely removed from the hyperdb, including all journal
        entries. It will no longer be available, and will generally break code
        if there are any references to the node.
        '''
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'
        self.db.destroynode(self.classname, nodeid)

    def history(self, nodeid):
        '''Retrieve the journal of edits on a particular node.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.

        The returned list contains tuples of the form

            (date, tag, action, params)

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
        all existing nodes must be unique or a ValueError is raised.
        '''
        # XXX create an index on the key prop column
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

    def lookup(self, keyvalue):
        '''Locate a particular node by its key property and return its id.

        If this class has no key property, a TypeError is raised.  If the
        'keyvalue' matches one of the values for the key property among
        the nodes in this class, the matching node's id is returned;
        otherwise a KeyError is raised.
        '''
        if not self.key:
            raise TypeError, 'No key property set'

        cursor = self.db.conn.cursor()
        sql = 'select id from _%s where _%s=?'%(self.classname, self.key)
        if __debug__:
            print >>hyperdb.DEBUG, 'lookup', (self, sql, keyvalue)
        cursor.execute(sql, (keyvalue,))

        # see if there was a result
        l = cursor.fetchall()
        if not l:
            raise KeyError, keyvalue

        # return the id
        return l[0][0]

    def find(self, **propspec):
        '''Get the ids of nodes in this class which link to the given nodes.

        'propspec' consists of keyword args propname={nodeid:1,}   
        'propname' must be the name of a property in this class, or a
        KeyError is raised.  That property must be a Link or Multilink
        property, or a TypeError is raised.

        Any node in this class whose 'propname' property links to any of the
        nodeids will be returned. Used by the full text indexing, which knows
        that "foo" occurs in msg1, msg3 and file7, so we have hits on these
        issues:

            db.issue.find(messages={'1':1,'3':1}, files={'7':1})
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'find', (self, propspec)
        if not propspec:
            return []
        queries = []
        tables = []
        allvalues = ()
        for prop, values in propspec.items():
            allvalues += tuple(values.keys())
            tables.append('select nodeid from %s_%s where linkid in (%s)'%(
                self.classname, prop, ','.join(['?' for x in values.keys()])))
        sql = '\nintersect\n'.join(tables)
        if __debug__:
            print >>hyperdb.DEBUG, 'find', (self, sql, allvalues)
        cursor = self.db.conn.cursor()
        cursor.execute(sql, allvalues)
        try:
            l = [x[0] for x in cursor.fetchall()]
        except gadfly.database.error, message:
            if message == 'no more results':
                l = []
            raise
        if __debug__:
            print >>hyperdb.DEBUG, 'find ... ', l
        return l

    def list(self):
        ''' Return a list of the ids of the active nodes in this class.
        '''
        return self.db.getnodeids(self.classname, retired=0)

    def filter(self, search_matches, filterspec, sort, group, 
            num_re = re.compile('^\d+$')):
        ''' Return a list of the ids of the active nodes in this class that
            match the 'filter' spec, sorted by the group spec and then the
            sort spec
        '''
        raise NotImplementedError

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
        '''
        d = self.properties.copy()
        if protected:
            d['id'] = String()
            d['creation'] = hyperdb.Date()
            d['activity'] = hyperdb.Date()
            d['creator'] = hyperdb.Link("user")
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
        content = proplist[i]
        del propnames[i]
        del proplist[i]

        # do the normal import
        newid = Class.import_list(self, propnames, proplist)

        # save off the "content" file
        self.db.storefile(self.classname, newid, None, content)
        return newid

    _marker = []
    def get(self, nodeid, propname, default=_marker, cache=1):
        ''' trap the content propname and get it from the file
        '''

        poss_msg = 'Possibly a access right configuration problem.'
        if propname == 'content':
            try:
                return self.db.getfile(self.classname, nodeid, None)
            except IOError, (strerror):
                # BUG: by catching this we donot see an error in the log.
                return 'ERROR reading file: %s%s\n%s\n%s'%(
                        self.classname, nodeid, poss_msg, strerror)
        if default is not self._marker:
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
        if protected:
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

# XXX deviation from spec - was called ItemClass
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
            properties['nosy'] = hyperdb.Multilink("user")
        if not properties.has_key('superseder'):
            properties['superseder'] = hyperdb.Multilink(classname)
        Class.__init__(self, db, classname, **properties)

#
# $Log: not supported by cvs2svn $
# Revision 1.1  2002/08/22 07:56:51  richard
# Whee! It's not finished yet, but I can create a new instance and play with
# it a little bit :)
#
# Revision 1.80  2002/08/16 04:28:13  richard
# added is_retired query to Class
#
# Revision 1.79  2002/07/29 23:30:14  richard
# documentation reorg post-new-security
#
# Revision 1.78  2002/07/21 03:26:37  richard
# Gordon, does this help?
#
# Revision 1.77  2002/07/18 11:27:47  richard
# ws
#
# Revision 1.76  2002/07/18 11:17:30  gmcm
# Add Number and Boolean types to hyperdb.
# Add conversion cases to web, mail & admin interfaces.
# Add storage/serialization cases to back_anydbm & back_metakit.
#
# Revision 1.75  2002/07/14 02:05:53  richard
# . all storage-specific code (ie. backend) is now implemented by the backends
#
# Revision 1.74  2002/07/10 00:24:10  richard
# braino
#
# Revision 1.73  2002/07/10 00:19:48  richard
# Added explicit closing of backend database handles.
#
# Revision 1.72  2002/07/09 21:53:38  gmcm
# Optimize Class.find so that the propspec can contain a set of ids to match.
# This is used by indexer.search so it can do just one find for all the index matches.
# This was already confusing code, but for common terms (lots of index matches),
# it is enormously faster.
#
# Revision 1.71  2002/07/09 03:02:52  richard
# More indexer work:
# - all String properties may now be indexed too. Currently there's a bit of
#   "issue" specific code in the actual searching which needs to be
#   addressed. In a nutshell:
#   + pass 'indexme="yes"' as a String() property initialisation arg, eg:
#         file = FileClass(db, "file", name=String(), type=String(),
#             comment=String(indexme="yes"))
#   + the comment will then be indexed and be searchable, with the results
#     related back to the issue that the file is linked to
# - as a result of this work, the FileClass has a default MIME type that may
#   be overridden in a subclass, or by the use of a "type" property as is
#   done in the default templates.
# - the regeneration of the indexes (if necessary) is done once the schema is
#   set up in the dbinit.
#
# Revision 1.70  2002/06/27 12:06:20  gmcm
# Improve an error message.
#
# Revision 1.69  2002/06/17 23:15:29  richard
# Can debug to stdout now
#
# Revision 1.68  2002/06/11 06:52:03  richard
#  . #564271 ] find() and new properties
#
# Revision 1.67  2002/06/11 05:02:37  richard
#  . #565979 ] code error in hyperdb.Class.find
#
# Revision 1.66  2002/05/25 07:16:24  rochecompaan
# Merged search_indexing-branch with HEAD
#
# Revision 1.65  2002/05/22 04:12:05  richard
#  . applied patch #558876 ] cgi client customization
#    ... with significant additions and modifications ;)
#    - extended handling of ML assignedto to all places it's handled
#    - added more NotFound info
#
# Revision 1.64  2002/05/15 06:21:21  richard
#  . node caching now works, and gives a small boost in performance
#
# As a part of this, I cleaned up the DEBUG output and implemented TRACE
# output (HYPERDBTRACE='file to trace to') with checkpoints at the start of
# CGI requests. Run roundup with python -O to skip all the DEBUG/TRACE stuff
# (using if __debug__ which is compiled out with -O)
#
# Revision 1.63  2002/04/15 23:25:15  richard
# . node ids are now generated from a lockable store - no more race conditions
#
# We're using the portalocker code by Jonathan Feinberg that was contributed
# to the ASPN Python cookbook. This gives us locking across Unix and Windows.
#
# Revision 1.62  2002/04/03 07:05:50  richard
# d'oh! killed retirement of nodes :(
# all better now...
#
# Revision 1.61  2002/04/03 06:11:51  richard
# Fix for old databases that contain properties that don't exist any more.
#
# Revision 1.60  2002/04/03 05:54:31  richard
# Fixed serialisation problem by moving the serialisation step out of the
# hyperdb.Class (get, set) into the hyperdb.Database.
#
# Also fixed htmltemplate after the showid changes I made yesterday.
#
# Unit tests for all of the above written.
#
# Revision 1.59.2.2  2002/04/20 13:23:33  rochecompaan
# We now have a separate search page for nodes.  Search links for
# different classes can be customized in instance_config similar to
# index links.
#
# Revision 1.59.2.1  2002/04/19 19:54:42  rochecompaan
# cgi_client.py
#     removed search link for the time being
#     moved rendering of matches to htmltemplate
# hyperdb.py
#     filtering of nodes on full text search incorporated in filter method
# roundupdb.py
#     added paramater to call of filter method
# roundup_indexer.py
#     added search method to RoundupIndexer class
#
# Revision 1.59  2002/03/12 22:52:26  richard
# more pychecker warnings removed
#
# Revision 1.58  2002/02/27 03:23:16  richard
# Ran it through pychecker, made fixes
#
# Revision 1.57  2002/02/20 05:23:24  richard
# Didn't accomodate new values for new properties
#
# Revision 1.56  2002/02/20 05:05:28  richard
#  . Added simple editing for classes that don't define a templated interface.
#    - access using the admin "class list" interface
#    - limited to admin-only
#    - requires the csv module from object-craft (url given if it's missing)
#
# Revision 1.55  2002/02/15 07:27:12  richard
# Oops, precedences around the way w0rng.
#
# Revision 1.54  2002/02/15 07:08:44  richard
#  . Alternate email addresses are now available for users. See the MIGRATION
#    file for info on how to activate the feature.
#
# Revision 1.53  2002/01/22 07:21:13  richard
# . fixed back_bsddb so it passed the journal tests
#
# ... it didn't seem happy using the back_anydbm _open method, which is odd.
# Yet another occurrance of whichdb not being able to recognise older bsddb
# databases. Yadda yadda. Made the HYPERDBDEBUG stuff more sane in the
# process.
#
# Revision 1.52  2002/01/21 16:33:19  rochecompaan
# You can now use the roundup-admin tool to pack the database
#
# Revision 1.51  2002/01/21 03:01:29  richard
# brief docco on the do_journal argument
#
# Revision 1.50  2002/01/19 13:16:04  rochecompaan
# Journal entries for link and multilink properties can now be switched on
# or off.
#
# Revision 1.49  2002/01/16 07:02:57  richard
#  . lots of date/interval related changes:
#    - more relaxed date format for input
#
# Revision 1.48  2002/01/14 06:32:34  richard
#  . #502951 ] adding new properties to old database
#
# Revision 1.47  2002/01/14 02:20:15  richard
#  . changed all config accesses so they access either the instance or the
#    config attriubute on the db. This means that all config is obtained from
#    instance_config instead of the mish-mash of classes. This will make
#    switching to a ConfigParser setup easier too, I hope.
#
# At a minimum, this makes migration a _little_ easier (a lot easier in the
# 0.5.0 switch, I hope!)
#
# Revision 1.46  2002/01/07 10:42:23  richard
# oops
#
# Revision 1.45  2002/01/02 04:18:17  richard
# hyperdb docstrings
#
# Revision 1.44  2002/01/02 02:31:38  richard
# Sorry for the huge checkin message - I was only intending to implement #496356
# but I found a number of places where things had been broken by transactions:
#  . modified ROUNDUPDBSENDMAILDEBUG to be SENDMAILDEBUG and hold a filename
#    for _all_ roundup-generated smtp messages to be sent to.
#  . the transaction cache had broken the roundupdb.Class set() reactors
#  . newly-created author users in the mailgw weren't being committed to the db
#
# Stuff that made it into CHANGES.txt (ie. the stuff I was actually working
# on when I found that stuff :):
#  . #496356 ] Use threading in messages
#  . detectors were being registered multiple times
#  . added tests for mailgw
#  . much better attaching of erroneous messages in the mail gateway
#
# Revision 1.43  2001/12/20 06:13:24  rochecompaan
# Bugs fixed:
#   . Exception handling in hyperdb for strings-that-look-like numbers got
#     lost somewhere
#   . Internet Explorer submits full path for filename - we now strip away
#     the path
# Features added:
#   . Link and multilink properties are now displayed sorted in the cgi
#     interface
#
# Revision 1.42  2001/12/16 10:53:37  richard
# take a copy of the node dict so that the subsequent set
# operation doesn't modify the oldvalues structure
#
# Revision 1.41  2001/12/15 23:47:47  richard
# Cleaned up some bare except statements
#
# Revision 1.40  2001/12/14 23:42:57  richard
# yuck, a gdbm instance tests false :(
# I've left the debugging code in - it should be removed one day if we're ever
# _really_ anal about performace :)
#
# Revision 1.39  2001/12/02 05:06:16  richard
# . We now use weakrefs in the Classes to keep the database reference, so
#   the close() method on the database is no longer needed.
#   I bumped the minimum python requirement up to 2.1 accordingly.
# . #487480 ] roundup-server
# . #487476 ] INSTALL.txt
#
# I also cleaned up the change message / post-edit stuff in the cgi client.
# There's now a clearly marked "TODO: append the change note" where I believe
# the change note should be added there. The "changes" list will obviously
# have to be modified to be a dict of the changes, or somesuch.
#
# More testing needed.
#
# Revision 1.38  2001/12/01 07:17:50  richard
# . We now have basic transaction support! Information is only written to
#   the database when the commit() method is called. Only the anydbm
#   backend is modified in this way - neither of the bsddb backends have been.
#   The mail, admin and cgi interfaces all use commit (except the admin tool
#   doesn't have a commit command, so interactive users can't commit...)
# . Fixed login/registration forwarding the user to the right page (or not,
#   on a failure)
#
# Revision 1.37  2001/11/28 21:55:35  richard
#  . login_action and newuser_action return values were being ignored
#  . Woohoo! Found that bloody re-login bug that was killing the mail
#    gateway.
#  (also a minor cleanup in hyperdb)
#
# Revision 1.36  2001/11/27 03:16:09  richard
# Another place that wasn't handling missing properties.
#
# Revision 1.35  2001/11/22 15:46:42  jhermann
# Added module docstrings to all modules.
#
# Revision 1.34  2001/11/21 04:04:43  richard
# *sigh* more missing value handling
#
# Revision 1.33  2001/11/21 03:40:54  richard
# more new property handling
#
# Revision 1.32  2001/11/21 03:11:28  richard
# Better handling of new properties.
#
# Revision 1.31  2001/11/12 22:01:06  richard
# Fixed issues with nosy reaction and author copies.
#
# Revision 1.30  2001/11/09 10:11:08  richard
#  . roundup-admin now handles all hyperdb exceptions
#
# Revision 1.29  2001/10/27 00:17:41  richard
# Made Class.stringFind() do caseless matching.
#
# Revision 1.28  2001/10/21 04:44:50  richard
# bug #473124: UI inconsistency with Link fields.
#    This also prompted me to fix a fairly long-standing usability issue -
#    that of being able to turn off certain filters.
#
# Revision 1.27  2001/10/20 23:44:27  richard
# Hyperdatabase sorts strings-that-look-like-numbers as numbers now.
#
# Revision 1.26  2001/10/16 03:48:01  richard
# admin tool now complains if a "find" is attempted with a non-link property.
#
# Revision 1.25  2001/10/11 00:17:51  richard
# Reverted a change in hyperdb so the default value for missing property
# values in a create() is None and not '' (the empty string.) This obviously
# breaks CSV import/export - the string 'None' will be created in an
# export/import operation.
#
# Revision 1.24  2001/10/10 03:54:57  richard
# Added database importing and exporting through CSV files.
# Uses the csv module from object-craft for exporting if it's available.
# Requires the csv module for importing.
#
# Revision 1.23  2001/10/09 23:58:10  richard
# Moved the data stringification up into the hyperdb.Class class' get, set
# and create methods. This means that the data is also stringified for the
# journal call, and removes duplication of code from the backends. The
# backend code now only sees strings.
#
# Revision 1.22  2001/10/09 07:25:59  richard
# Added the Password property type. See "pydoc roundup.password" for
# implementation details. Have updated some of the documentation too.
#
# Revision 1.21  2001/10/05 02:23:24  richard
#  . roundup-admin create now prompts for property info if none is supplied
#    on the command-line.
#  . hyperdb Class getprops() method may now return only the mutable
#    properties.
#  . Login now uses cookies, which makes it a whole lot more flexible. We can
#    now support anonymous user access (read-only, unless there's an
#    "anonymous" user, in which case write access is permitted). Login
#    handling has been moved into cgi_client.Client.main()
#  . The "extended" schema is now the default in roundup init.
#  . The schemas have had their page headings modified to cope with the new
#    login handling. Existing installations should copy the interfaces.py
#    file from the roundup lib directory to their instance home.
#  . Incorrectly had a Bizar Software copyright on the cgitb.py module from
#    Ping - has been removed.
#  . Fixed a whole bunch of places in the CGI interface where we should have
#    been returning Not Found instead of throwing an exception.
#  . Fixed a deviation from the spec: trying to modify the 'id' property of
#    an item now throws an exception.
#
# Revision 1.20  2001/10/04 02:12:42  richard
# Added nicer command-line item adding: passing no arguments will enter an
# interactive more which asks for each property in turn. While I was at it, I
# fixed an implementation problem WRT the spec - I wasn't raising a
# ValueError if the key property was missing from a create(). Also added a
# protected=boolean argument to getprops() so we can list only the mutable
# properties (defaults to yes, which lists the immutables).
#
# Revision 1.19  2001/08/29 04:47:18  richard
# Fixed CGI client change messages so they actually include the properties
# changed (again).
#
# Revision 1.18  2001/08/16 07:34:59  richard
# better CGI text searching - but hidden filter fields are disappearing...
#
# Revision 1.17  2001/08/16 06:59:58  richard
# all searches use re now - and they're all case insensitive
#
# Revision 1.16  2001/08/15 23:43:18  richard
# Fixed some isFooTypes that I missed.
# Refactored some code in the CGI code.
#
# Revision 1.15  2001/08/12 06:32:36  richard
# using isinstance(blah, Foo) now instead of isFooType
#
# Revision 1.14  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.13  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.12  2001/08/02 06:38:17  richard
# Roundupdb now appends "mailing list" information to its messages which
# include the e-mail address and web interface address. Templates may
# override this in their db classes to include specific information (support
# instructions, etc).
#
# Revision 1.11  2001/08/01 04:24:21  richard
# mailgw was assuming certain properties existed on the issues being created.
#
# Revision 1.10  2001/07/30 02:38:31  richard
# get() now has a default arg - for migration only.
#
# Revision 1.9  2001/07/29 09:28:23  richard
# Fixed sorting by clicking on column headings.
#
# Revision 1.8  2001/07/29 08:27:40  richard
# Fixed handling of passed-in values in form elements (ie. during a
# drill-down)
#
# Revision 1.7  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.6  2001/07/29 05:36:14  richard
# Cleanup of the link label generation.
#
# Revision 1.5  2001/07/29 04:05:37  richard
# Added the fabricated property "id".
#
# Revision 1.4  2001/07/27 06:25:35  richard
# Fixed some of the exceptions so they're the right type.
# Removed the str()-ification of node ids so we don't mask oopsy errors any
# more.
#
# Revision 1.3  2001/07/27 05:17:14  richard
# just some comments
#
# Revision 1.2  2001/07/22 12:09:32  richard
# Final commit of Grande Splite
#
# Revision 1.1  2001/07/22 11:58:35  richard
# More Grande Splite
#
#
# vim: set filetype=python ts=4 sw=4 et si
