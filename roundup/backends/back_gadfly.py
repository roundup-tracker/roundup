# $Id: back_gadfly.py,v 1.18 2002-09-12 07:23:23 richard Exp $
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

        db = getattr(config, 'GADFLY_DATABASE', ('database', self.dir))
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
        return '<roundfly 0x%x>'%id(self)

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

    def setnode(self, classname, nodeid, node, multilink_changes):
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
        for col, (add, remove) in multilink_changes.items():
            tn = '%s_%s'%(classname, col)
            if add:
                sql = 'insert into %s (nodeid, linkid) values (?,?)'%tn
                vals = [(nodeid, addid) for addid in add]
                if __debug__:
                    print >>hyperdb.DEBUG, 'setnode (add)', (self, sql, vals)
                cursor.execute(sql, vals)
            if remove:
                sql = 'delete from %s where nodeid=? and linkid=?'%tn
                vals = [(nodeid, removeid) for removeid in remove]
                if __debug__:
                    print >>hyperdb.DEBUG, 'setnode (rem)', (self, sql, vals)
                cursor.execute(sql, vals)

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
        ''' Delete all journal entries except "create" before 'pack_before'.
        '''
        # get a 'yyyymmddhhmmss' version of the date
        date_stamp = pack_before.serialise()

        # do the delete
        cursor = self.conn.cursor()
        for classname in self.classes.keys():
            sql = "delete from %s__journal where date<? and "\
                "action<>'create'"%classname
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

    def close(self):
        ''' Close off the connection.
        '''
        self.conn.close()

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
            try:
                return self.db.user.lookup(name)
            except KeyError:
                # the journaltag user doesn't exist any more
                return None

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

        # don't pass our list to other code
        if isinstance(prop, Multilink):
            return d[propname][:]

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

        # remember the add/remove stuff for multilinks, making it easier
        # for the Database layer to do its stuff
        multilink_changes = {}

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
                multilink_changes[propname] = (add, remove)
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
        self.db.setnode(self.classname, nodeid, node, multilink_changes)

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
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'

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
            raise TypeError, 'No key property set for class %s'%self.classname

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

    def filter(self, search_matches, filterspec, sort, group):
        ''' Return a list of the ids of the active nodes in this class that
            match the 'filter' spec, sorted by the group spec and then the
            sort spec

            "filterspec" is {propname: value(s)}
            "sort" and "group" are (dir, prop) where dir is '+', '-' or None
                               and prop is a prop name or None
            "search_matches" is {nodeid: marker}
        '''
        cn = self.classname

        # figure the WHERE clause from the filterspec
        props = self.getprops()
        frum = ['_'+cn]
        where = []
        args = []
        for k, v in filterspec.items():
            propclass = props[k]
            if isinstance(propclass, Multilink):
                tn = '%s_%s'%(cn, k)
                frum.append(tn)
                if isinstance(v, type([])):
                    s = ','.join(['?' for x in v])
                    where.append('id=%s.nodeid and %s.linkid in (%s)'%(tn,tn,s))
                    args = args + v
                else:
                    where.append('id=%s.nodeid and %s.linkid = ?'%(tn, tn))
                    args.append(v)
            else:
                if isinstance(v, type([])):
                    s = ','.join(['?' for x in v])
                    where.append('_%s in (%s)'%(k, s))
                    args = args + v
                else:
                    where.append('_%s=?'%k)
                    args.append(v)

        # add results of full text search
        if search_matches is not None:
            v = search_matches.keys()
            s = ','.join(['?' for x in v])
            where.append('id in (%s)'%s)
            args = args + v

        # figure the order by clause
        orderby = []
        ordercols = []
        if sort[0] is not None and sort[1] is not None:
            if sort[0] != '-':
                orderby.append('_'+sort[1])
                ordercols.append(sort[1])
            else:
                orderby.append('_'+sort[1]+' desc')
                ordercols.append(sort[1])

        # figure the group by clause
        groupby = []
        groupcols = []
        if group[0] is not None and group[1] is not None:
            if group[0] != '-':
                groupby.append('_'+group[1])
                groupcols.append(group[1])
            else:
                groupby.append('_'+group[1]+' desc')
                groupcols.append(group[1])

        # construct the SQL
        frum = ','.join(frum)
        where = ' and '.join(where)
        cols = ['id']
        if orderby:
            cols = cols + ordercols
            order = ' order by %s'%(','.join(orderby))
        else:
            order = ''
        if groupby:
            cols = cols + groupcols
            group = ' group by %s'%(','.join(groupby))
        else:
            group = ''
        cols = ','.join(cols)
        sql = 'select %s from %s where %s%s%s'%(cols, frum, where, order,
            group)
        args = tuple(args)
        if __debug__:
            print >>hyperdb.DEBUG, 'find', (self, sql, args)
        cursor = self.db.conn.cursor()
        cursor.execute(sql, args)

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
            # note: journalling is turned off as it really just wastes
            # space. this behaviour may be overridden in an instance
            properties['nosy'] = hyperdb.Multilink("user", do_journal="no")
        if not properties.has_key('superseder'):
            properties['superseder'] = hyperdb.Multilink(classname)
        Class.__init__(self, db, classname, **properties)
