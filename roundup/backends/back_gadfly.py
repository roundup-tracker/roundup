# $Id: back_gadfly.py,v 1.31.2.3 2003-03-14 02:52:03 richard Exp $
''' Gadlfy relational database hypderb backend.

About Gadfly
============

Gadfly  is  a  collection  of  python modules that provides relational
database  functionality  entirely implemented in Python. It supports a
subset  of  the intergalactic standard RDBMS Structured Query Language
SQL.


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
from roundup.backends import locking

# basic RDBMS backen implementation
from roundup.backends import rdbms_common

# the all-important gadfly :)
import gadfly
import gadfly.client
import gadfly.database

class Database(rdbms_common.Database):
    # char to use for positional arguments
    arg = '?'

    def open_connection(self):
        db = getattr(self.config, 'GADFLY_DATABASE', ('database', self.dir))

        # lock it
        lockfilenm = os.path.join(db[1], db[0]) + '.lck'
        self.lockfile = locking.acquire_lock(lockfilenm)
        self.lockfile.write(str(os.getpid()))
        self.lockfile.flush()

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
                self.cursor = self.conn.cursor()
                self.cursor.execute('create table schema (schema varchar)')
                self.cursor.execute('create table ids (name varchar, num integer)')
            else:
                self.cursor = self.conn.cursor()
                self.cursor.execute('select schema from schema')
                self.database_schema = self.cursor.fetchone()[0]
        else:
            self.conn = gadfly.client.gfclient(*db)
            self.database_schema = self.load_dbschema()

    def __repr__(self):
        return '<roundfly 0x%x>'%id(self)

    def sql_fetchone(self):
        ''' Fetch a single row. If there's nothing to fetch, return None.
        '''
        try:
            return self.cursor.fetchone()
        except gadfly.database.error, message:
            if message == 'no more results':
                return None
            raise

    def sql_fetchall(self):
        ''' Fetch a single row. If there's nothing to fetch, return [].
        '''
        try:
            return self.cursor.fetchall()
        except gadfly.database.error, message:
            if message == 'no more results':
                return []
            raise

    def save_dbschema(self, schema):
        ''' Save the schema definition that the database currently implements
        '''
        self.sql('insert into schema values (?)', (self.database_schema,))

    def load_dbschema(self):
        ''' Load the schema definition that the database currently implements
        '''
        self.cursor.execute('select schema from schema')
        return self.cursor.fetchone()[0]

    def save_journal(self, classname, cols, nodeid, journaldate,
            journaltag, action, params):
        ''' Save the journal entry to the database
        '''
        # nothing special to do
        entry = (nodeid, journaldate, journaltag, action, params)

        # do the insert
        a = self.arg
        sql = 'insert into %s__journal (%s) values (?,?,?,?,?)'%(classname,
            cols)
        if __debug__:
            print >>hyperdb.DEBUG, 'addjournal', (self, sql, entry)
        self.cursor.execute(sql, entry)

    def load_journal(self, classname, cols, nodeid):
        ''' Load the journal from the database
        '''
        # now get the journal entries
        sql = 'select %s from %s__journal where nodeid=%s'%(cols, classname,
            self.arg)
        if __debug__:
            print >>hyperdb.DEBUG, 'getjournal', (self, sql, nodeid)
        self.cursor.execute(sql, (nodeid,))
        res = []
        for nodeid, date_stamp, user, action, params in self.cursor.fetchall():
            res.append((nodeid, date.Date(date_stamp), user, action, params))
        return res

    def update_class(self, spec, old_spec):
        ''' Determine the differences between the current spec and the
            database version of the spec, and update where necessary

            GADFLY requires a commit after the table drop!
        '''
        new_spec = spec
        new_has = new_spec.properties.has_key

        new_spec = new_spec.schema()
        new_spec[1].sort()
        old_spec[1].sort()
        if new_spec == old_spec:
            # no changes
            return 0

        if __debug__:
            print >>hyperdb.DEBUG, 'update_class FIRING'

        # key property changed?
        if old_spec[0] != new_spec[0]:
            if __debug__:
                print >>hyperdb.DEBUG, 'update_class setting keyprop', `spec[0]`
            # XXX turn on indexing for the key property

        # detect multilinks that have been removed, and drop their table
        old_has = {}
        for name,prop in old_spec[1]:
            old_has[name] = 1
            if not new_has(name) and isinstance(prop, Multilink):
                # it's a multilink, and it's been removed - drop the old
                # table
                sql = 'drop table %s_%s'%(spec.classname, prop)
                if __debug__:
                    print >>hyperdb.DEBUG, 'update_class', (self, sql)
                self.cursor.execute(sql)
                continue
        old_has = old_has.has_key

        # now figure how we populate the new table
        fetch = ['_activity', '_creation', '_creator']
        properties = spec.getprops()
        for propname,x in new_spec[1]:
            prop = properties[propname]
            if isinstance(prop, Multilink):
                if not old_has(propname):
                    # we need to create the new table
                    self.create_multilink_table(spec, propname)
            elif old_has(propname):
                # we copy this col over from the old table
                fetch.append('_'+propname)

        # select the data out of the old table
        fetch.append('id')
        fetch.append('__retired__')
        fetchcols = ','.join(fetch)
        cn = spec.classname
        sql = 'select %s from _%s'%(fetchcols, cn)
        if __debug__:
            print >>hyperdb.DEBUG, 'update_class', (self, sql)
        self.cursor.execute(sql)
        olddata = self.cursor.fetchall()

        # drop the old table
        self.cursor.execute('drop table _%s'%cn)

        # GADFLY requires a commit here, or the table spec screws up
        self.conn.commit()

        # create the new table
        cols, mls = self.create_class_table(spec)

        # figure the new columns
        extra = 0
        for col in cols:
            if col not in fetch:
                fetch.append(col)
                extra += 1

        if olddata:
            # do the insert
            fetchcols = ','.join(fetch)
            args = ','.join([self.arg for x in fetch])
            sql = 'insert into _%s (%s) values (%s)'%(cn, fetchcols, args)
            if __debug__:
                print >>hyperdb.DEBUG, 'update_class', (self, sql, olddata[0])
            for entry in olddata:
                self.cursor.execute(sql, tuple(entry) + (None,)*extra)

        return 1

class GadflyClass:
    def filter(self, search_matches, filterspec, sort=(None,None),
            group=(None,None)):
        ''' Gadfly doesn't have a LIKE predicate :(
        '''
        cn = self.classname

        # figure the WHERE clause from the filterspec
        props = self.getprops()
        frum = ['_'+cn]
        where = []
        args = []
        a = self.db.arg
        for k, v in filterspec.items():
            propclass = props[k]
            if isinstance(propclass, Multilink):
                tn = '%s_%s'%(cn, k)
                frum.append(tn)
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('id=%s.nodeid and %s.linkid in (%s)'%(tn,tn,s))
                    args = args + v
                else:
                    where.append('id=%s.nodeid and %s.linkid = %s'%(tn, tn, a))
                    args.append(v)
            elif isinstance(propclass, Date):
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s in (%s)'%(k, s))
                    args = args + [date.Date(x).serialise() for x in v]
                else:
                    where.append('_%s=%s'%(k, a))
                    args.append(date.Date(v).serialise())
            elif isinstance(propclass, Interval):
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s in (%s)'%(k, s))
                    args = args + [date.Interval(x).serialise() for x in v]
                else:
                    where.append('_%s=%s'%(k, a))
                    args.append(date.Interval(v).serialise())
            elif k == 'id':
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('%s in (%s)'%(k, s))
                    args = args + v
                else:
                    where.append('%s=%s'%(k, a))
                    args.append(v)
            else:
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s in (%s)'%(k, s))
                    args = args + v
                else:
                    where.append('_%s=%s'%(k, a))
                    args.append(v)

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
        self.db.cursor.execute(sql, args)
        l = self.db.cursor.fetchall()

        # return the IDs
        return [row[0] for row in l]

    def find(self, **propspec):
        ''' Overload to filter out duplicates in the result
        '''
        d = {}
        for k in rdbms_common.Class.find(self, **propspec):
            d[k] = 1
        return d.keys()

class Class(GadflyClass, rdbms_common.Class):
    pass
class IssueClass(GadflyClass, rdbms_common.IssueClass):
    pass
class FileClass(GadflyClass, rdbms_common.FileClass):
    pass

