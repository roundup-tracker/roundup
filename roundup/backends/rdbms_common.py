# $Id: rdbms_common.py,v 1.85 2004-03-24 03:07:52 richard Exp $
''' Relational database (SQL) backend common code.

Basics:

- map roundup classes to relational tables
- automatically detect schema changes and modify the table schemas
  appropriately (we store the "database version" of the schema in the
  database itself as the only row of the "schema" table)
- multilinks (which represent a many-to-many relationship) are handled through
  intermediate tables
- journals are stored adjunct to the per-class tables
- table names and columns have "_" prepended so the names can't clash with
  restricted names (like "order")
- retirement is determined by the __retired__ column being true

Database-specific changes may generally be pushed out to the overridable
sql_* methods, since everything else should be fairly generic. There's
probably a bit of work to be done if a database is used that actually
honors column typing, since the initial databases don't (sqlite stores
everything as a string.)

The schema of the hyperdb being mapped to the database is stored in the
database itself as a repr()'ed dictionary of information about each Class
that maps to a table. If that information differs from the hyperdb schema,
then we update it. We also store in the schema dict a version which
allows us to upgrade the database schema when necessary. See upgrade_db().
'''
__docformat__ = 'restructuredtext'

# standard python modules
import sys, os, time, re, errno, weakref, copy

# roundup modules
from roundup import hyperdb, date, password, roundupdb, security
from roundup.hyperdb import String, Password, Date, Interval, Link, \
    Multilink, DatabaseError, Boolean, Number, Node
from roundup.backends import locking

# support
from blobfiles import FileStorage
from indexer_rdbms import Indexer
from sessions_rdbms import Sessions, OneTimeKeys
from roundup.date import Range

# number of rows to keep in memory
ROW_CACHE_SIZE = 100

def _num_cvt(num):
    num = str(num)
    try:
        return int(num)
    except:
        return float(num)

class Database(FileStorage, hyperdb.Database, roundupdb.Database):
    ''' Wrapper around an SQL database that presents a hyperdb interface.

        - some functionality is specific to the actual SQL database, hence
          the sql_* methods that are NotImplemented
        - we keep a cache of the latest ROW_CACHE_SIZE row fetches.
    '''
    def __init__(self, config, journaltag=None):
        ''' Open the database and load the schema from it.
        '''
        self.config, self.journaltag = config, journaltag
        self.dir = config.DATABASE
        self.classes = {}
        self.indexer = Indexer(self)
        self.security = security.Security(self)

        # additional transaction support for external files and the like
        self.transactions = []

        # keep a cache of the N most recently retrieved rows of any kind
        # (classname, nodeid) = row
        self.cache = {}
        self.cache_lru = []

        # database lock
        self.lockfile = None

        # open a connection to the database, creating the "conn" attribute
        self.open_connection()

    def clearCache(self):
        self.cache = {}
        self.cache_lru = []

    def getSessionManager(self):
        return Sessions(self)

    def getOTKManager(self):
        return OneTimeKeys(self)

    def open_connection(self):
        ''' Open a connection to the database, creating it if necessary.

            Must call self.load_dbschema()
        '''
        raise NotImplemented

    def sql(self, sql, args=None):
        ''' Execute the sql with the optional args.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, (self, sql, args)
        if args:
            self.cursor.execute(sql, args)
        else:
            self.cursor.execute(sql)

    def sql_fetchone(self):
        ''' Fetch a single row. If there's nothing to fetch, return None.
        '''
        return self.cursor.fetchone()

    def sql_fetchall(self):
        ''' Fetch all rows. If there's nothing to fetch, return [].
        '''
        return self.cursor.fetchall()

    def sql_stringquote(self, value):
        ''' Quote the string so it's safe to put in the 'sql quotes'
        '''
        return re.sub("'", "''", str(value))

    def init_dbschema(self):
        self.database_schema = {
            'version': self.current_db_version,
            'tables': {}
        }

    def load_dbschema(self):
        ''' Load the schema definition that the database currently implements
        '''
        self.cursor.execute('select schema from schema')
        schema = self.cursor.fetchone()
        if schema:
            self.database_schema = eval(schema[0])
        else:
            self.database_schema = {}

    def save_dbschema(self, schema):
        ''' Save the schema definition that the database currently implements
        '''
        s = repr(self.database_schema)
        self.sql('insert into schema values (%s)', (s,))

    def post_init(self):
        ''' Called once the schema initialisation has finished.

            We should now confirm that the schema defined by our "classes"
            attribute actually matches the schema in the database.
        '''
        save = self.upgrade_db()

        # now detect changes in the schema
        tables = self.database_schema['tables']
        for classname, spec in self.classes.items():
            if tables.has_key(classname):
                dbspec = tables[classname]
                if self.update_class(spec, dbspec):
                    tables[classname] = spec.schema()
                    save = 1
            else:
                self.create_class(spec)
                tables[classname] = spec.schema()
                save = 1

        for classname, spec in tables.items():
            if not self.classes.has_key(classname):
                self.drop_class(classname, tables[classname])
                del tables[classname]
                save = 1

        # update the database version of the schema
        if save:
            self.sql('delete from schema')
            self.save_dbschema(self.database_schema)

        # reindex the db if necessary
        if self.indexer.should_reindex():
            self.reindex()

        # commit
        self.sql_commit()

    # update this number when we need to make changes to the SQL structure
    # of the backen database
    current_db_version = 2
    def upgrade_db(self):
        ''' Update the SQL database to reflect changes in the backend code.

            Return boolean whether we need to save the schema.
        '''
        version = self.database_schema.get('version', 1)
        if version == self.current_db_version:
            # nothing to do
            return 0

        if version == 1:
            # change the schema structure
            self.database_schema = {'tables': self.database_schema}

            # version 1 didn't have the actor column (note that in
            # MySQL this will also transition the tables to typed columns)
            self.add_actor_column()

            # version 1 doesn't have the OTK, session and indexing in the
            # database
            self.create_version_2_tables()

        self.database_schema['version'] = self.current_db_version
        return 1


    def refresh_database(self):
        self.post_init()

    def reindex(self):
        for klass in self.classes.values():
            for nodeid in klass.list():
                klass.index(nodeid)
        self.indexer.save_index()


    hyperdb_to_sql_datatypes = {
        hyperdb.String : 'VARCHAR(255)',
        hyperdb.Date   : 'TIMESTAMP',
        hyperdb.Link   : 'INTEGER',
        hyperdb.Interval  : 'VARCHAR(255)',
        hyperdb.Password  : 'VARCHAR(255)',
        hyperdb.Boolean   : 'INTEGER',
        hyperdb.Number    : 'REAL',
    }
    def determine_columns(self, properties):
        ''' Figure the column names and multilink properties from the spec

            "properties" is a list of (name, prop) where prop may be an
            instance of a hyperdb "type" _or_ a string repr of that type.
        '''
        cols = [
            ('_actor', self.hyperdb_to_sql_datatypes[hyperdb.Link]),
            ('_activity', self.hyperdb_to_sql_datatypes[hyperdb.Date]),
            ('_creator', self.hyperdb_to_sql_datatypes[hyperdb.Link]),
            ('_creation', self.hyperdb_to_sql_datatypes[hyperdb.Date]),
        ]
        mls = []
        # add the multilinks separately
        for col, prop in properties:
            if isinstance(prop, Multilink):
                mls.append(col)
                continue

            if isinstance(prop, type('')):
                raise ValueError, "string property spec!"
                #and prop.find('Multilink') != -1:
                #mls.append(col)

            datatype = self.hyperdb_to_sql_datatypes[prop.__class__]
            cols.append(('_'+col, datatype))

        cols.sort()
        return cols, mls

    def update_class(self, spec, old_spec, force=0):
        ''' Determine the differences between the current spec and the
            database version of the spec, and update where necessary.

            If 'force' is true, update the database anyway.
        '''
        new_has = spec.properties.has_key
        new_spec = spec.schema()
        new_spec[1].sort()
        old_spec[1].sort()
        if not force and new_spec == old_spec:
            # no changes
            return 0

        if __debug__:
            print >>hyperdb.DEBUG, 'update_class FIRING'

        # detect key prop change for potential index change
        keyprop_changes = {}
        if new_spec[0] != old_spec[0]:
            keyprop_changes = {'remove': old_spec[0], 'add': new_spec[0]}

        # detect multilinks that have been removed, and drop their table
        old_has = {}
        for name, prop in old_spec[1]:
            old_has[name] = 1
            if new_has(name):
                continue

            if prop.find('Multilink to') != -1:
                # first drop indexes.
                self.drop_multilink_table_indexes(spec.classname, name)

                # now the multilink table itself
                sql = 'drop table %s_%s'%(spec.classname, name)
            else:
                # if this is the key prop, drop the index first
                if old_spec[0] == prop:
                    self.drop_class_table_key_index(spec.classname, name)
                    del keyprop_changes['remove']

                # drop the column
                sql = 'alter table _%s drop column _%s'%(spec.classname, name)

            if __debug__:
                print >>hyperdb.DEBUG, 'update_class', (self, sql)
            self.cursor.execute(sql)
        old_has = old_has.has_key

        # if we didn't remove the key prop just then, but the key prop has
        # changed, we still need to remove the old index
        if keyprop_changes.has_key('remove'):
            self.drop_class_table_key_index(spec.classname,
                keyprop_changes['remove'])

        # add new columns
        for propname, x in new_spec[1]:
            if old_has(propname):
                continue
            sql = 'alter table _%s add column _%s varchar(255)'%(
                spec.classname, propname)
            if __debug__:
                print >>hyperdb.DEBUG, 'update_class', (self, sql)
            self.cursor.execute(sql)

            # if the new column is a key prop, we need an index!
            if new_spec[0] == propname:
                self.create_class_table_key_index(spec.classname, propname)
                del keyprop_changes['add']

        # if we didn't add the key prop just then, but the key prop has
        # changed, we still need to add the new index
        if keyprop_changes.has_key('add'):
            self.create_class_table_key_index(spec.classname,
                keyprop_changes['add'])

        return 1

    def create_class_table(self, spec):
        '''Create the class table for the given Class "spec". Creates the
        indexes too.'''
        cols, mls = self.determine_columns(spec.properties.items())

        # add on our special columns
        cols.append(('id', 'INTEGER PRIMARY KEY'))
        cols.append(('__retired__', 'INTEGER DEFAULT 0'))

        # create the base table
        scols = ','.join(['%s %s'%x for x in cols])
        sql = 'create table _%s (%s)'%(spec.classname, scols)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)

        self.create_class_table_indexes(spec)

        return cols, mls

    def create_class_table_indexes(self, spec):
        ''' create the class table for the given spec
        '''
        # create __retired__ index
        index_sql2 = 'create index _%s_retired_idx on _%s(__retired__)'%(
                        spec.classname, spec.classname)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_index', (self, index_sql2)
        self.cursor.execute(index_sql2)

        # create index for key property
        if spec.key:
            if __debug__:
                print >>hyperdb.DEBUG, 'update_class setting keyprop %r'% \
                    spec.key
            index_sql3 = 'create index _%s_%s_idx on _%s(_%s)'%(
                        spec.classname, spec.key,
                        spec.classname, spec.key)
            if __debug__:
                print >>hyperdb.DEBUG, 'create_index', (self, index_sql3)
            self.cursor.execute(index_sql3)

    def drop_class_table_indexes(self, cn, key):
        # drop the old table indexes first
        l = ['_%s_id_idx'%cn, '_%s_retired_idx'%cn]
        if key:
            l.append('_%s_%s_idx'%(cn, key))

        table_name = '_%s'%cn
        for index_name in l:
            if not self.sql_index_exists(table_name, index_name):
                continue
            index_sql = 'drop index '+index_name
            if __debug__:
                print >>hyperdb.DEBUG, 'drop_index', (self, index_sql)
            self.cursor.execute(index_sql)

    def create_class_table_key_index(self, cn, key):
        ''' create the class table for the given spec
        '''
        sql = 'create index _%s_%s_idx on _%s(_%s)'%(cn, key, cn, key)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class_tab_key_index', (self, sql)
        self.cursor.execute(sql)

    def drop_class_table_key_index(self, cn, key):
        table_name = '_%s'%cn
        index_name = '_%s_%s_idx'%(cn, key)
        if not self.sql_index_exists(table_name, index_name):
            return
        sql = 'drop index '+index_name
        if __debug__:
            print >>hyperdb.DEBUG, 'drop_class_tab_key_index', (self, sql)
        self.cursor.execute(sql)

    def create_journal_table(self, spec):
        ''' create the journal table for a class given the spec and 
            already-determined cols
        '''
        # journal table
        cols = ','.join(['%s varchar'%x
            for x in 'nodeid date tag action params'.split()])
        sql = '''create table %s__journal (
            nodeid integer, date timestamp, tag varchar(255),
            action varchar(255), params varchar(25))'''%spec.classname
        if __debug__:
            print >>hyperdb.DEBUG, 'create_journal_table', (self, sql)
        self.cursor.execute(sql)
        self.create_journal_table_indexes(spec)

    def create_journal_table_indexes(self, spec):
        # index on nodeid
        sql = 'create index %s_journ_idx on %s__journal(nodeid)'%(
                        spec.classname, spec.classname)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_index', (self, sql)
        self.cursor.execute(sql)

    def drop_journal_table_indexes(self, classname):
        index_name = '%s_journ_idx'%classname
        if not self.sql_index_exists('%s__journal'%classname, index_name):
            return
        index_sql = 'drop index '+index_name
        if __debug__:
            print >>hyperdb.DEBUG, 'drop_index', (self, index_sql)
        self.cursor.execute(index_sql)

    def create_multilink_table(self, spec, ml):
        ''' Create a multilink table for the "ml" property of the class
            given by the spec
        '''
        # create the table
        sql = 'create table %s_%s (linkid varchar, nodeid varchar)'%(
            spec.classname, ml)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)
        self.create_multilink_table_indexes(spec, ml)

    def create_multilink_table_indexes(self, spec, ml):
        # create index on linkid
        index_sql = 'create index %s_%s_l_idx on %s_%s(linkid)'%(
            spec.classname, ml, spec.classname, ml)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_index', (self, index_sql)
        self.cursor.execute(index_sql)

        # create index on nodeid
        index_sql = 'create index %s_%s_n_idx on %s_%s(nodeid)'%(
            spec.classname, ml, spec.classname, ml)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_index', (self, index_sql)
        self.cursor.execute(index_sql)

    def drop_multilink_table_indexes(self, classname, ml):
        l = [
            '%s_%s_l_idx'%(classname, ml),
            '%s_%s_n_idx'%(classname, ml)
        ]
        table_name = '%s_%s'%(classname, ml)
        for index_name in l:
            if not self.sql_index_exists(table_name, index_name):
                continue
            index_sql = 'drop index %s'%index_name
            if __debug__:
                print >>hyperdb.DEBUG, 'drop_index', (self, index_sql)
            self.cursor.execute(index_sql)

    def create_class(self, spec):
        ''' Create a database table according to the given spec.
        '''
        cols, mls = self.create_class_table(spec)
        self.create_journal_table(spec)

        # now create the multilink tables
        for ml in mls:
            self.create_multilink_table(spec, ml)

    def drop_class(self, cn, spec):
        ''' Drop the given table from the database.

            Drop the journal and multilink tables too.
        '''
        properties = spec[1]
        # figure the multilinks
        mls = []
        for propanme, prop in properties:
            if isinstance(prop, Multilink):
                mls.append(propname)

        # drop class table and indexes
        self.drop_class_table_indexes(cn, spec[0])

        self.drop_class_table(cn)

        # drop journal table and indexes
        self.drop_journal_table_indexes(cn)
        sql = 'drop table %s__journal'%cn
        if __debug__:
            print >>hyperdb.DEBUG, 'drop_class', (self, sql)
        self.cursor.execute(sql)

        for ml in mls:
            # drop multilink table and indexes
            self.drop_multilink_table_indexes(cn, ml)
            sql = 'drop table %s_%s'%(spec.classname, ml)
            if __debug__:
                print >>hyperdb.DEBUG, 'drop_class', (self, sql)
            self.cursor.execute(sql)

    def drop_class_table(self, cn):
        sql = 'drop table _%s'%cn
        if __debug__:
            print >>hyperdb.DEBUG, 'drop_class', (self, sql)
        self.cursor.execute(sql)

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

        # add default Edit and View permissions
        self.security.addPermission(name="Edit", klass=cn,
            description="User is allowed to edit "+cn)
        self.security.addPermission(name="View", klass=cn,
            description="User is allowed to access "+cn)

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
        try:
            return self.classes[classname]
        except KeyError:
            raise KeyError, 'There is no class called "%s"'%classname

    def clear(self):
        '''Delete all database contents.

        Note: I don't commit here, which is different behaviour to the
              "nuke from orbit" behaviour in the dbs.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'clear', (self,)
        for cn in self.classes.keys():
            sql = 'delete from _%s'%cn
            if __debug__:
                print >>hyperdb.DEBUG, 'clear', (self, sql)
            self.cursor.execute(sql)

    #
    # Nodes
    #

    hyperdb_to_sql_value = {
        hyperdb.String : str,
        hyperdb.Date   : lambda x: x.formal(sep=' ', sec='%f'),
        hyperdb.Link   : int,
        hyperdb.Interval  : lambda x: x.serialise(),
        hyperdb.Password  : str,
        hyperdb.Boolean   : int,
        hyperdb.Number    : lambda x: x,
    }
    def addnode(self, classname, nodeid, node):
        ''' Add the specified node to its class's db.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'addnode', (self, classname, nodeid, node)

        # determine the column definitions and multilink tables
        cl = self.classes[classname]
        cols, mls = self.determine_columns(cl.properties.items())

        # we'll be supplied these props if we're doing an import
        values = node.copy()
        if not values.has_key('creator'):
            # add in the "calculated" properties (dupe so we don't affect
            # calling code's node assumptions)
            values['creation'] = values['activity'] = date.Date()
            values['actor'] = values['creator'] = self.getuid()

        cl = self.classes[classname]
        props = cl.getprops(protected=1)
        del props['id']

        # default the non-multilink columns
        for col, prop in props.items():
            if not values.has_key(col):
                if isinstance(prop, Multilink):
                    values[col] = []
                else:
                    values[col] = None

        # clear this node out of the cache if it's in there
        key = (classname, nodeid)
        if self.cache.has_key(key):
            del self.cache[key]
            self.cache_lru.remove(key)

        # figure the values to insert
        vals = []
        for col,dt in cols:
            prop = props[col[1:]]
            value = values[col[1:]]
            if value:
                value = self.hyperdb_to_sql_value[prop.__class__](value)
            vals.append(value)
        vals.append(nodeid)
        vals = tuple(vals)

        # make sure the ordering is correct for column name -> column value
        s = ','.join([self.arg for x in cols]) + ',%s'%self.arg
        cols = ','.join([col for col,dt in cols]) + ',id'

        # perform the inserts
        sql = 'insert into _%s (%s) values (%s)'%(classname, cols, s)
        if __debug__:
            print >>hyperdb.DEBUG, 'addnode', (self, sql, vals)
        self.cursor.execute(sql, vals)

        # insert the multilink rows
        for col in mls:
            t = '%s_%s'%(classname, col)
            for entry in node[col]:
                sql = 'insert into %s (linkid, nodeid) values (%s,%s)'%(t,
                    self.arg, self.arg)
                self.sql(sql, (entry, nodeid))

        # make sure we do the commit-time extra stuff for this node
        self.transactions.append((self.doSaveNode, (classname, nodeid, node)))

    def setnode(self, classname, nodeid, values, multilink_changes):
        ''' Change the specified node.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'setnode', (self, classname, nodeid, values)

        # clear this node out of the cache if it's in there
        key = (classname, nodeid)
        if self.cache.has_key(key):
            del self.cache[key]
            self.cache_lru.remove(key)

        # add the special props
        values = values.copy()
        values['activity'] = date.Date()
        values['actor'] = self.getuid()

        cl = self.classes[classname]
        props = cl.getprops()

        cols = []
        mls = []
        # add the multilinks separately
        for col in values.keys():
            prop = props[col]
            if isinstance(prop, Multilink):
                mls.append(col)
            else:
                cols.append(col)
        cols.sort()

        # figure the values to insert
        vals = []
        for col in cols:
            prop = props[col]
            value = values[col]
            if value is not None:
                value = self.hyperdb_to_sql_value[prop.__class__](value)
            vals.append(value)
        vals.append(int(nodeid))
        vals = tuple(vals)

        # if there's any updates to regular columns, do them
        if cols:
            # make sure the ordering is correct for column name -> column value
            s = ','.join(['_%s=%s'%(x, self.arg) for x in cols])
            cols = ','.join(cols)

            # perform the update
            sql = 'update _%s set %s where id=%s'%(classname, s, self.arg)
            if __debug__:
                print >>hyperdb.DEBUG, 'setnode', (self, sql, vals)
            self.cursor.execute(sql, vals)

        # now the fun bit, updating the multilinks ;)
        for col, (add, remove) in multilink_changes.items():
            tn = '%s_%s'%(classname, col)
            if add:
                sql = 'insert into %s (nodeid, linkid) values (%s,%s)'%(tn,
                    self.arg, self.arg)
                for addid in add:
                    # XXX numeric ids
                    self.sql(sql, (int(nodeid), int(addid)))
            if remove:
                sql = 'delete from %s where nodeid=%s and linkid=%s'%(tn,
                    self.arg, self.arg)
                for removeid in remove:
                    # XXX numeric ids
                    self.sql(sql, (int(nodeid), int(removeid)))

        # make sure we do the commit-time extra stuff for this node
        self.transactions.append((self.doSaveNode, (classname, nodeid, values)))

    sql_to_hyperdb_value = {
        hyperdb.String : str,
        hyperdb.Date   : lambda x:date.Date(str(x).replace(' ', '.')),
#        hyperdb.Link   : int,      # XXX numeric ids
        hyperdb.Link   : str,
        hyperdb.Interval  : date.Interval,
        hyperdb.Password  : lambda x: password.Password(encrypted=x),
        hyperdb.Boolean   : int,
        hyperdb.Number    : _num_cvt,
    }
    def getnode(self, classname, nodeid):
        ''' Get a node from the database.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'getnode', (self, classname, nodeid)

        # see if we have this node cached
        key = (classname, nodeid)
        if self.cache.has_key(key):
            # push us back to the top of the LRU
            self.cache_lru.remove(key)
            self.cache_lru.insert(0, key)
            # return the cached information
            return self.cache[key]

        # figure the columns we're fetching
        cl = self.classes[classname]
        cols, mls = self.determine_columns(cl.properties.items())
        scols = ','.join([col for col,dt in cols])

        # perform the basic property fetch
        sql = 'select %s from _%s where id=%s'%(scols, classname, self.arg)
        self.sql(sql, (nodeid,))

        values = self.sql_fetchone()
        if values is None:
            raise IndexError, 'no such %s node %s'%(classname, nodeid)

        # make up the node
        node = {}
        props = cl.getprops(protected=1)
        for col in range(len(cols)):
            name = cols[col][0][1:]
            value = values[col]
            if value is not None:
                value = self.sql_to_hyperdb_value[props[name].__class__](value)
            node[name] = value


        # now the multilinks
        for col in mls:
            # get the link ids
            sql = 'select linkid from %s_%s where nodeid=%s'%(classname, col,
                self.arg)
            self.cursor.execute(sql, (nodeid,))
            # extract the first column from the result
            # XXX numeric ids
            node[col] = [str(x[0]) for x in self.cursor.fetchall()]

        # save off in the cache
        key = (classname, nodeid)
        self.cache[key] = node
        # update the LRU
        self.cache_lru.insert(0, key)
        if len(self.cache_lru) > ROW_CACHE_SIZE:
            del self.cache[self.cache_lru.pop()]

        return node

    def destroynode(self, classname, nodeid):
        '''Remove a node from the database. Called exclusively by the
           destroy() method on Class.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'destroynode', (self, classname, nodeid)

        # make sure the node exists
        if not self.hasnode(classname, nodeid):
            raise IndexError, '%s has no node %s'%(classname, nodeid)

        # see if we have this node cached
        if self.cache.has_key((classname, nodeid)):
            del self.cache[(classname, nodeid)]

        # see if there's any obvious commit actions that we should get rid of
        for entry in self.transactions[:]:
            if entry[1][:2] == (classname, nodeid):
                self.transactions.remove(entry)

        # now do the SQL
        sql = 'delete from _%s where id=%s'%(classname, self.arg)
        self.sql(sql, (nodeid,))

        # remove from multilnks
        cl = self.getclass(classname)
        x, mls = self.determine_columns(cl.properties.items())
        for col in mls:
            # get the link ids
            sql = 'delete from %s_%s where nodeid=%s'%(classname, col, self.arg)
            self.sql(sql, (nodeid,))

        # remove journal entries
        sql = 'delete from %s__journal where nodeid=%s'%(classname, self.arg)
        self.sql(sql, (nodeid,))

    def hasnode(self, classname, nodeid):
        ''' Determine if the database has a given node.
        '''
        sql = 'select count(*) from _%s where id=%s'%(classname, self.arg)
        if __debug__:
            print >>hyperdb.DEBUG, 'hasnode', (self, sql, nodeid)
        self.cursor.execute(sql, (nodeid,))
        return int(self.cursor.fetchone()[0])

    def countnodes(self, classname):
        ''' Count the number of nodes that exist for a particular Class.
        '''
        sql = 'select count(*) from _%s'%classname
        if __debug__:
            print >>hyperdb.DEBUG, 'countnodes', (self, sql)
        self.cursor.execute(sql)
        return self.cursor.fetchone()[0]

    def addjournal(self, classname, nodeid, action, params, creator=None,
            creation=None):
        ''' Journal the Action
        'action' may be:

            'create' or 'set' -- 'params' is a dictionary of property values
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retire' -- 'params' is None
        '''
        # serialise the parameters now if necessary
        if isinstance(params, type({})):
            if action in ('set', 'create'):
                params = self.serialise(classname, params)

        # handle supply of the special journalling parameters (usually
        # supplied on importing an existing database)
        if creator:
            journaltag = creator
        else:
            journaltag = self.getuid()
        if creation:
            journaldate = creation
        else:
            journaldate = date.Date()

        # create the journal entry
        cols = ','.join('nodeid date tag action params'.split())

        if __debug__:
            print >>hyperdb.DEBUG, 'addjournal', (nodeid, journaldate,
                journaltag, action, params)

        self.save_journal(classname, cols, nodeid, journaldate,
            journaltag, action, params)

    def getjournal(self, classname, nodeid):
        ''' get the journal for id
        '''
        # make sure the node exists
        if not self.hasnode(classname, nodeid):
            raise IndexError, '%s has no node %s'%(classname, nodeid)

        cols = ','.join('nodeid date tag action params'.split())
        return self.load_journal(classname, cols, nodeid)

    def save_journal(self, classname, cols, nodeid, journaldate,
            journaltag, action, params):
        ''' Save the journal entry to the database
        '''
        # make the params db-friendly
        params = repr(params)
        dc = self.hyperdb_to_sql_value[hyperdb.Date]
        entry = (nodeid, dc(journaldate), journaltag, action, params)

        # do the insert
        a = self.arg
        sql = 'insert into %s__journal (%s) values (%s,%s,%s,%s,%s)'%(
            classname, cols, a, a, a, a, a)
        if __debug__:
            print >>hyperdb.DEBUG, 'save_journal', (self, sql, entry)
        self.cursor.execute(sql, entry)

    def load_journal(self, classname, cols, nodeid):
        ''' Load the journal from the database
        '''
        # now get the journal entries
        sql = 'select %s from %s__journal where nodeid=%s order by date'%(
            cols, classname, self.arg)
        if __debug__:
            print >>hyperdb.DEBUG, 'load_journal', (self, sql, nodeid)
        self.cursor.execute(sql, (nodeid,))
        res = []
        dc = self.sql_to_hyperdb_value[hyperdb.Date]
        for nodeid, date_stamp, user, action, params in self.cursor.fetchall():
            params = eval(params)
            # XXX numeric ids
            res.append((str(nodeid), dc(date_stamp), user, action, params))
        return res

    def pack(self, pack_before):
        ''' Delete all journal entries except "create" before 'pack_before'.
        '''
        # get a 'yyyymmddhhmmss' version of the date
        date_stamp = pack_before.serialise()

        # do the delete
        for classname in self.classes.keys():
            sql = "delete from %s__journal where date<%s and "\
                "action<>'create'"%(classname, self.arg)
            if __debug__:
                print >>hyperdb.DEBUG, 'pack', (self, sql, date_stamp)
            self.cursor.execute(sql, (date_stamp,))

    def sql_commit(self):
        ''' Actually commit to the database.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, '+++ commit database connection +++'
        self.conn.commit()

    def commit(self):
        ''' Commit the current transactions.

        Save all data changed since the database was opened or since the
        last commit() or rollback().
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'commit', (self,)

        # commit the database
        self.sql_commit()

        # now, do all the other transaction stuff
        for method, args in self.transactions:
            method(*args)

        # save the indexer state
        self.indexer.save_index()

        # clear out the transactions
        self.transactions = []

    def sql_rollback(self):
        self.conn.rollback()

    def rollback(self):
        ''' Reverse all actions from the current transaction.

        Undo all the changes made since the database was opened or the last
        commit() or rollback() was performed.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'rollback', (self,)

        self.sql_rollback()

        # roll back "other" transaction stuff
        for method, args in self.transactions:
            # delete temporary files
            if method == self.doStoreFile:
                self.rollbackStoreFile(*args)
        self.transactions = []

        # clear the cache
        self.clearCache()

    def doSaveNode(self, classname, nodeid, node):
        ''' dummy that just generates a reindex event
        '''
        # return the classname, nodeid so we reindex this content
        return (classname, nodeid)

    def sql_close(self):
        if __debug__:
            print >>hyperdb.DEBUG, '+++ close database connection +++'
        self.conn.close()

    def close(self):
        ''' Close off the connection.
        '''
        self.indexer.close()
        self.sql_close()

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
        for name in 'creation activity creator actor'.split():
            if properties.has_key(name):
                raise ValueError, '"creation", "activity", "creator" and '\
                    '"actor" are reserved'

        self.classname = classname
        self.properties = properties
        self.db = weakref.proxy(db)       # use a weak ref to avoid circularity
        self.key = ''

        # should we journal changes (default yes)
        self.do_journal = 1

        # do the db-related init stuff
        db.addclass(self)

        self.auditors = {'create': [], 'set': [], 'retire': [], 'restore': []}
        self.reactors = {'create': [], 'set': [], 'retire': [], 'restore': []}

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
        self.fireAuditors('create', None, propvalues)
        newid = self.create_inner(**propvalues)
        self.fireReactors('create', newid, None)
        return newid
    
    def create_inner(self, **propvalues):
        ''' Called by create, in-between the audit and react calls.
        '''
        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'

        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'

        if propvalues.has_key('creator') or propvalues.has_key('actor') or \
             propvalues.has_key('creation') or propvalues.has_key('activity'):
            raise KeyError, '"creator", "actor", "creation" and '\
                '"activity" are reserved'

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
                if type(value) != type('') and type(value) != type(u''):
                    raise TypeError, 'new property "%s" not a string'%key
                self.db.indexer.add_text((self.classname, newid, key), value)

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
            self.db.addjournal(self.classname, newid, 'create', {})

        # XXX numeric ids
        return str(newid)

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
        l.append(repr(self.is_retired(nodeid)))
        return l

    def import_list(self, propnames, proplist):
        ''' Import a node - all information including "id" is present and
            should not be sanity checked. Triggers are not triggered. The
            journal should be initialised using the "creator" and "created"
            information.

            Return the nodeid of the node imported.
        '''
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'
        properties = self.getprops()

        # make the new node's property map
        d = {}
        retire = 0
        newid = None
        for i in range(len(propnames)):
            # Use eval to reverse the repr() used to output the CSV
            value = eval(proplist[i])

            # Figure the property for this column
            propname = propnames[i]

            # "unmarshal" where necessary
            if propname == 'id':
                newid = value
                continue
            elif propname == 'is retired':
                # is the item retired?
                if int(value):
                    retire = 1
                continue
            elif value is None:
                d[propname] = None
                continue

            prop = properties[propname]
            if value is None:
                # don't set Nones
                continue
            elif isinstance(prop, hyperdb.Date):
                value = date.Date(value)
            elif isinstance(prop, hyperdb.Interval):
                value = date.Interval(value)
            elif isinstance(prop, hyperdb.Password):
                pwd = password.Password()
                pwd.unpack(value)
                value = pwd
            d[propname] = value

        # get a new id if necessary
        if newid is None:
            newid = self.db.newid(self.classname)

        # add the node and journal
        self.db.addnode(self.classname, newid, d)

        # retire?
        if retire:
            # use the arg for __retired__ to cope with any odd database type
            # conversion (hello, sqlite)
            sql = 'update _%s set __retired__=%s where id=%s'%(self.classname,
                self.db.arg, self.db.arg)
            if __debug__:
                print >>hyperdb.DEBUG, 'retire', (self, sql, newid)
            self.db.cursor.execute(sql, (1, newid))

        # extract the extraneous journalling gumpf and nuke it
        if d.has_key('creator'):
            creator = d['creator']
            del d['creator']
        else:
            creator = None
        if d.has_key('creation'):
            creation = d['creation']
            del d['creation']
        else:
            creation = None
        if d.has_key('activity'):
            del d['activity']
        if d.has_key('actor'):
            del d['actor']
        self.db.addjournal(self.classname, newid, 'create', {}, creator,
            creation)
        return newid

    _marker = []
    def get(self, nodeid, propname, default=_marker, cache=1):
        '''Get the value of a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.  'propname' must be the name of a property
        of this class or a KeyError is raised.

        'cache' exists for backwards compatibility, and is not used.
        '''
        if propname == 'id':
            return nodeid

        # get the node's dict
        d = self.db.getnode(self.classname, nodeid)

        if propname == 'creation':
            if d.has_key('creation'):
                return d['creation']
            else:
                return date.Date()
        if propname == 'activity':
            if d.has_key('activity'):
                return d['activity']
            else:
                return date.Date()
        if propname == 'creator':
            if d.has_key('creator'):
                return d['creator']
            else:
                return self.db.getuid()
        if propname == 'actor':
            if d.has_key('actor'):
                return d['actor']
            else:
                return self.db.getuid()

        # get the property (raises KeyErorr if invalid)
        prop = self.properties[propname]

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
        oldvalues = copy.deepcopy(self.db.getnode(self.classname, nodeid))
        propvalues = self.set_inner(nodeid, **propvalues)
        self.fireReactors('set', nodeid, oldvalues)
        return propvalues        

    def set_inner(self, nodeid, **propvalues):
        ''' Called by set, in-between the audit and react calls.
        ''' 
        if not propvalues:
            return propvalues

        if propvalues.has_key('creation') or propvalues.has_key('creator') or \
                propvalues.has_key('actor') or propvalues.has_key('activity'):
            raise KeyError, '"creation", "creator", "actor" and '\
                '"activity" are reserved'

        if propvalues.has_key('id'):
            raise KeyError, '"id" is reserved'

        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'

        node = self.db.getnode(self.classname, nodeid)
        if self.is_retired(nodeid):
            raise IndexError, 'Requested item is retired'
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
            try:
                prop = self.properties[propname]
            except KeyError:
                raise KeyError, '"%s" has no property named "%s"'%(
                    self.classname, propname)

            # if the value's the same as the existing value, no sense in
            # doing anything
            current = node.get(propname, None)
            if value == current:
                del propvalues[propname]
                continue
            journalvalues[propname] = current

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
                if value is not None and type(value) != type('') and type(value) != type(u''):
                    raise TypeError, 'new property "%s" not a string'%propname
                self.db.indexer.add_text((self.classname, nodeid, propname),
                    value)

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

        # nothing to do?
        if not propvalues:
            return propvalues

        # do the set, and journal it
        self.db.setnode(self.classname, nodeid, propvalues, multilink_changes)

        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, 'set', journalvalues)

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

        self.fireAuditors('retire', nodeid, None)

        # use the arg for __retired__ to cope with any odd database type
        # conversion (hello, sqlite)
        sql = 'update _%s set __retired__=%s where id=%s'%(self.classname,
            self.db.arg, self.db.arg)
        if __debug__:
            print >>hyperdb.DEBUG, 'retire', (self, sql, nodeid)
        self.db.cursor.execute(sql, (1, nodeid))
        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, 'retired', None)

        self.fireReactors('retire', nodeid, None)

    def restore(self, nodeid):
        '''Restore a retired node.

        Make node available for all operations like it was before retirement.
        '''
        if self.db.journaltag is None:
            raise DatabaseError, 'Database open read-only'

        node = self.db.getnode(self.classname, nodeid)
        # check if key property was overrided
        key = self.getkey()
        try:
            id = self.lookup(node[key])
        except KeyError:
            pass
        else:
            raise KeyError, "Key property (%s) of retired node clashes with \
                existing one (%s)" % (key, node[key])

        self.fireAuditors('restore', nodeid, None)
        # use the arg for __retired__ to cope with any odd database type
        # conversion (hello, sqlite)
        sql = 'update _%s set __retired__=%s where id=%s'%(self.classname,
            self.db.arg, self.db.arg)
        if __debug__:
            print >>hyperdb.DEBUG, 'restore', (self, sql, nodeid)
        self.db.cursor.execute(sql, (0, nodeid))
        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, 'restored', None)

        self.fireReactors('restore', nodeid, None)
        
    def is_retired(self, nodeid):
        '''Return true if the node is rerired
        '''
        sql = 'select __retired__ from _%s where id=%s'%(self.classname,
            self.db.arg)
        if __debug__:
            print >>hyperdb.DEBUG, 'is_retired', (self, sql, nodeid)
        self.db.cursor.execute(sql, (nodeid,))
        return int(self.db.sql_fetchone()[0])

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

            (nodeid, date, tag, action, params)

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
        # XXX create an index on the key prop column. We should also 
        # record that we've created this index in the schema somewhere.
        prop = self.getprops()[propname]
        if not isinstance(prop, String):
            raise TypeError, 'key properties must be String'
        self.key = propname

    def getkey(self):
        '''Return the name of the key property for this class or None.'''
        return self.key

    def labelprop(self, default_to_id=0):
        '''Return the property name for a label for the given node.

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

        # use the arg to handle any odd database type conversion (hello,
        # sqlite)
        sql = "select id from _%s where _%s=%s and __retired__ <> %s"%(
            self.classname, self.key, self.db.arg, self.db.arg)
        self.db.sql(sql, (keyvalue, 1))

        # see if there was a result that's not retired
        row = self.db.sql_fetchone()
        if not row:
            raise KeyError, 'No key (%s) value "%s" for "%s"'%(self.key,
                keyvalue, self.classname)

        # return the id
        # XXX numeric ids
        return str(row[0])

    def find(self, **propspec):
        '''Get the ids of nodes in this class which link to the given nodes.

        'propspec' consists of keyword args propname=nodeid or
                   propname={nodeid:1, }
        'propname' must be the name of a property in this class, or a
                   KeyError is raised.  That property must be a Link or
                   Multilink property, or a TypeError is raised.

        Any node in this class whose 'propname' property links to any of the
        nodeids will be returned. Used by the full text indexing, which knows
        that "foo" occurs in msg1, msg3 and file7, so we have hits on these
        issues:

            db.issue.find(messages={'1':1,'3':1}, files={'7':1})
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'find', (self, propspec)

        # shortcut
        if not propspec:
            return []

        # validate the args
        props = self.getprops()
        propspec = propspec.items()
        for propname, nodeids in propspec:
            # check the prop is OK
            prop = props[propname]
            if not isinstance(prop, Link) and not isinstance(prop, Multilink):
                raise TypeError, "'%s' not a Link/Multilink property"%propname

        # first, links
        a = self.db.arg
        allvalues = (1,)
        o = []
        where = []
        for prop, values in propspec:
            if not isinstance(props[prop], hyperdb.Link):
                continue
            if type(values) is type({}) and len(values) == 1:
                values = values.keys()[0]
            if type(values) is type(''):
                allvalues += (values,)
                where.append('_%s = %s'%(prop, a))
            elif values is None:
                where.append('_%s is NULL'%prop)
            else:
                allvalues += tuple(values.keys())
                where.append('_%s in (%s)'%(prop, ','.join([a]*len(values))))
        tables = ['_%s'%self.classname]
        if where:
            o.append('(' + ' and '.join(where) + ')')

        # now multilinks
        for prop, values in propspec:
            if not isinstance(props[prop], hyperdb.Multilink):
                continue
            if not values:
                continue
            if type(values) is type(''):
                allvalues += (values,)
                s = a
            else:
                allvalues += tuple(values.keys())
                s = ','.join([a]*len(values))
            tn = '%s_%s'%(self.classname, prop)
            tables.append(tn)
            o.append('(id=%s.nodeid and %s.linkid in (%s))'%(tn, tn, s))

        if not o:
            return []
        elif len(o) > 1:
            o = '(' + ' or '.join(['(%s)'%i for i in o]) + ')'
        else:
            o = o[0]
        t = ', '.join(tables)
        sql = 'select distinct(id) from %s where __retired__ <> %s and %s'%(
            t, a, o)
        self.db.sql(sql, allvalues)
        # XXX numeric ids
        l = [str(x[0]) for x in self.db.sql_fetchall()]
        if __debug__:
            print >>hyperdb.DEBUG, 'find ... ', l
        return l

    def stringFind(self, **requirements):
        '''Locate a particular node by matching a set of its String
        properties in a caseless search.

        If the property is not a String property, a TypeError is raised.
        
        The return is a list of the id of all nodes that match.
        '''
        where = []
        args = []
        for propname in requirements.keys():
            prop = self.properties[propname]
            if not isinstance(prop, String):
                raise TypeError, "'%s' not a String property"%propname
            where.append(propname)
            args.append(requirements[propname].lower())

        # generate the where clause
        s = ' and '.join(['lower(_%s)=%s'%(col, self.db.arg) for col in where])
        sql = 'select id from _%s where %s and __retired__=%s'%(self.classname,
            s, self.db.arg)
        args.append(0)
        self.db.sql(sql, tuple(args))
        # XXX numeric ids
        l = [str(x[0]) for x in self.db.sql_fetchall()]
        if __debug__:
            print >>hyperdb.DEBUG, 'find ... ', l
        return l

    def list(self):
        ''' Return a list of the ids of the active nodes in this class.
        '''
        return self.getnodeids(retired=0)

    def getnodeids(self, retired=None):
        ''' Retrieve all the ids of the nodes for a particular Class.

            Set retired=None to get all nodes. Otherwise it'll get all the 
            retired or non-retired nodes, depending on the flag.
        '''
        # flip the sense of the 'retired' flag if we don't want all of them
        if retired is not None:
            if retired:
                args = (0, )
            else:
                args = (1, )
            sql = 'select id from _%s where __retired__ <> %s'%(self.classname,
                self.db.arg)
        else:
            args = ()
            sql = 'select id from _%s'%self.classname
        if __debug__:
            print >>hyperdb.DEBUG, 'getnodeids', (self, sql, retired)
        self.db.cursor.execute(sql, args)
        # XXX numeric ids
        ids = [str(x[0]) for x in self.db.cursor.fetchall()]
        return ids

    def filter(self, search_matches, filterspec, sort=(None,None),
            group=(None,None)):
        '''Return a list of the ids of the active nodes in this class that
        match the 'filter' spec, sorted by the group spec and then the
        sort spec

        "filterspec" is {propname: value(s)}

        "sort" and "group" are (dir, prop) where dir is '+', '-' or None
        and prop is a prop name or None

        "search_matches" is {nodeid: marker}

        The filter must match all properties specificed - but if the
        property value to match is a list, any one of the values in the
        list may match for that property to match.
        '''
        # just don't bother if the full-text search matched diddly
        if search_matches == {}:
            return []

        cn = self.classname

        timezone = self.db.getUserTimezone()
        
        # figure the WHERE clause from the filterspec
        props = self.getprops()
        frum = ['_'+cn]
        where = []
        args = []
        a = self.db.arg
        for k, v in filterspec.items():
            propclass = props[k]
            # now do other where clause stuff
            if isinstance(propclass, Multilink):
                tn = '%s_%s'%(cn, k)
                if v in ('-1', ['-1']):
                    # only match rows that have count(linkid)=0 in the
                    # corresponding multilink table)
                    where.append('id not in (select nodeid from %s)'%tn)
                elif isinstance(v, type([])):
                    frum.append(tn)
                    s = ','.join([a for x in v])
                    where.append('id=%s.nodeid and %s.linkid in (%s)'%(tn,tn,s))
                    args = args + v
                else:
                    frum.append(tn)
                    where.append('id=%s.nodeid and %s.linkid=%s'%(tn, tn, a))
                    args.append(v)
            elif k == 'id':
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('%s in (%s)'%(k, s))
                    args = args + v
                else:
                    where.append('%s=%s'%(k, a))
                    args.append(v)
            elif isinstance(propclass, String):
                if not isinstance(v, type([])):
                    v = [v]

                # Quote the bits in the string that need it and then embed
                # in a "substring" search. Note - need to quote the '%' so
                # they make it through the python layer happily
                v = ['%%'+self.db.sql_stringquote(s)+'%%' for s in v]

                # now add to the where clause
                where.append(' or '.join(["_%s LIKE '%s'"%(k, s) for s in v]))
                # note: args are embedded in the query string now
            elif isinstance(propclass, Link):
                if isinstance(v, type([])):
                    if '-1' in v:
                        v = v[:]
                        v.remove('-1')
                        xtra = ' or _%s is NULL'%k
                    else:
                        xtra = ''
                    if v:
                        s = ','.join([a for x in v])
                        where.append('(_%s in (%s)%s)'%(k, s, xtra))
                        args = args + v
                    else:
                        where.append('_%s is NULL'%k)
                else:
                    if v == '-1':
                        v = None
                        where.append('_%s is NULL'%k)
                    else:
                        where.append('_%s=%s'%(k, a))
                        args.append(v)
            elif isinstance(propclass, Date):
                dc = self.db.hyperdb_to_sql_value[hyperdb.Date]
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s in (%s)'%(k, s))
                    args = args + [dc(date.Date(v)) for x in v]
                else:
                    try:
                        # Try to filter on range of dates
                        date_rng = Range(v, date.Date, offset=timezone)
                        if date_rng.from_value:
                            where.append('_%s >= %s'%(k, a))                            
                            args.append(dc(date_rng.from_value))
                        if date_rng.to_value:
                            where.append('_%s <= %s'%(k, a))
                            args.append(dc(date_rng.to_value))
                    except ValueError:
                        # If range creation fails - ignore that search parameter
                        pass                        
            elif isinstance(propclass, Interval):
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s in (%s)'%(k, s))
                    args = args + [date.Interval(x).serialise() for x in v]
                else:
                    try:
                        # Try to filter on range of intervals
                        date_rng = Range(v, date.Interval)
                        if date_rng.from_value:
                            where.append('_%s >= %s'%(k, a))
                            args.append(date_rng.from_value.serialise())
                        if date_rng.to_value:
                            where.append('_%s <= %s'%(k, a))
                            args.append(date_rng.to_value.serialise())
                    except ValueError:
                        # If range creation fails - ignore that search parameter
                        pass                        
                    #where.append('_%s=%s'%(k, a))
                    #args.append(date.Interval(v).serialise())
            else:
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s in (%s)'%(k, s))
                    args = args + v
                else:
                    where.append('_%s=%s'%(k, a))
                    args.append(v)

        # don't match retired nodes
        where.append('__retired__ <> 1')

        # add results of full text search
        if search_matches is not None:
            v = search_matches.keys()
            s = ','.join([a for x in v])
            where.append('id in (%s)'%s)
            args = args + v

        # "grouping" is just the first-order sorting in the SQL fetch
        # can modify it...)
        orderby = []
        ordercols = []
        if group[0] is not None and group[1] is not None:
            if group[0] != '-':
                orderby.append('_'+group[1])
                ordercols.append('_'+group[1])
            else:
                orderby.append('_'+group[1]+' desc')
                ordercols.append('_'+group[1])

        # now add in the sorting
        group = ''
        if sort[0] is not None and sort[1] is not None:
            direction, colname = sort
            if direction != '-':
                if colname == 'id':
                    orderby.append(colname)
                else:
                    orderby.append('_'+colname)
                    ordercols.append('_'+colname)
            else:
                if colname == 'id':
                    orderby.append(colname+' desc')
                    ordercols.append(colname)
                else:
                    orderby.append('_'+colname+' desc')
                    ordercols.append('_'+colname)

        # construct the SQL
        frum = ','.join(frum)
        if where:
            where = ' where ' + (' and '.join(where))
        else:
            where = ''
        cols = ['id']
        if orderby:
            cols = cols + ordercols
            order = ' order by %s'%(','.join(orderby))
        else:
            order = ''
        cols = ','.join(cols)
        sql = 'select %s from %s %s%s%s'%(cols, frum, where, group, order)
        args = tuple(args)
        if __debug__:
            print >>hyperdb.DEBUG, 'filter', (self, sql, args)
        if args:
            self.db.cursor.execute(sql, args)
        else:
            # psycopg doesn't like empty args
            self.db.cursor.execute(sql)
        l = self.db.sql_fetchall()

        # return the IDs (the first column)
        # XXX numeric ids
        return [str(row[0]) for row in l]

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
            d['creator'] = hyperdb.Link('user')
            d['actor'] = hyperdb.Link('user')
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
                self.db.indexer.add_text((self.classname, nodeid, prop),
                    str(self.get(nodeid, prop)))


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

class FileClass(Class, hyperdb.FileClass):
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
        # we need to fire the auditors now, or the content property won't
        # be in propvalues for the auditors to play with
        self.fireAuditors('create', None, propvalues)

        # now remove the content property so it's not stored in the db
        content = propvalues['content']
        del propvalues['content']

        # do the database create
        newid = self.create_inner(**propvalues)

        # figure the mime type
        mime_type = propvalues.get('type', self.default_mime_type)

        # and index!
        self.db.indexer.add_text((self.classname, newid, 'content'), content,
            mime_type)

        # fire reactors
        self.fireReactors('create', newid, None)

        # store off the content as a file
        self.db.storefile(self.classname, newid, None, content)
        return newid

    def import_list(self, propnames, proplist):
        ''' Trap the "content" property...
        '''
        # dupe this list so we don't affect others
        propnames = propnames[:]

        # extract the "content" property from the proplist
        i = propnames.index('content')
        content = eval(proplist[i])
        del propnames[i]
        del proplist[i]

        # do the normal import
        newid = Class.import_list(self, propnames, proplist)

        # save off the "content" file
        self.db.storefile(self.classname, newid, None, content)
        return newid

    _marker = []
    def get(self, nodeid, propname, default=_marker, cache=1):
        ''' Trap the content propname and get it from the file

        'cache' exists for backwards compatibility, and is not used.
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
            return Class.get(self, nodeid, propname, default)
        else:
            return Class.get(self, nodeid, propname)

    def getprops(self, protected=1):
        ''' In addition to the actual properties on the node, these methods
            provide the "content" property. If the "protected" flag is true,
            we include protected properties - those which may not be
            modified.
        '''
        d = Class.getprops(self, protected=protected).copy()
        d['content'] = hyperdb.String()
        return d

    def set(self, itemid, **propvalues):
        ''' Snarf the "content" propvalue and update it in a file
        '''
        self.fireAuditors('set', itemid, propvalues)
        oldvalues = copy.deepcopy(self.db.getnode(self.classname, itemid))

        # now remove the content property so it's not stored in the db
        content = None
        if propvalues.has_key('content'):
            content = propvalues['content']
            del propvalues['content']

        # do the database create
        propvalues = self.set_inner(itemid, **propvalues)

        # do content?
        if content:
            # store and index
            self.db.storefile(self.classname, itemid, None, content)
            mime_type = propvalues.get('type', self.get(itemid, 'type'))
            if not mime_type:
                mime_type = self.default_mime_type
            self.db.indexer.add_text((self.classname, itemid, 'content'),
                content, mime_type)

        # fire reactors
        self.fireReactors('set', itemid, oldvalues)
        return propvalues

# XXX deviation from spec - was called ItemClass
class IssueClass(Class, roundupdb.IssueClass):
    # Overridden methods:
    def __init__(self, db, classname, **properties):
        '''The newly-created class automatically includes the "messages",
        "files", "nosy", and "superseder" properties.  If the 'properties'
        dictionary attempts to specify any of these properties or a
        "creation", "creator", "activity" or "actor" property, a ValueError
        is raised.
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

