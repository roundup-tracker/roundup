# $Id: back_gadfly.py,v 1.23 2002-09-19 02:37:41 richard Exp $
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

from roundup.backends.rdbms_common import *

# the all-important gadfly :)
import gadfly
import gadfly.client
import gadfly.database

class Database(Database):
    # char to use for positional arguments
    arg = '?'

    def open_connection(self):
        db = getattr(self.config, 'GADFLY_DATABASE', ('database', self.dir))
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
            self.database_schema = self.load_dbschema(cursor)

    def __repr__(self):
        return '<roundfly 0x%x>'%id(self)

    def sql_fetchone(self, cursor):
        ''' Fetch a single row. If there's nothing to fetch, return None.
        '''
        try:
            return cursor.fetchone()
        except gadfly.database.error, message:
            if message == 'no more results':
                return None
            raise

    def save_dbschema(self, cursor, schema):
        ''' Save the schema definition that the database currently implements
        '''
        self.sql(cursor, 'insert into schema values (?)',
            (self.database_schema,))

    def load_dbschema(self, cursor):
        ''' Load the schema definition that the database currently implements
        '''
        cursor.execute('select schema from schema')
        return cursor.fetchone()[0]

    def save_journal(self, cursor, classname, cols, nodeid, journaldate,
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
        cursor.execute(sql, entry)

    def load_journal(self, cursor, classname, cols, nodeid):
        ''' Load the journal from the database
        '''
        # now get the journal entries
        sql = 'select %s from %s__journal where nodeid=%s'%(cols, classname,
            self.arg)
        if __debug__:
            print >>hyperdb.DEBUG, 'getjournal', (self, sql, nodeid)
        cursor.execute(sql, (nodeid,))
        res = []
        for nodeid, date_stamp, user, action, params in cursor.fetchall():
            res.append((nodeid, date.Date(date_stamp), user, action, params))
        return res

class GadflyClass:
    def filter(self, search_matches, filterspec, sort, group):
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
                    s = ','.join([self.arg for x in v])
                    where.append('id=%s.nodeid and %s.linkid in (%s)'%(tn,tn,s))
                    args = args + v
                else:
                    where.append('id=%s.nodeid and %s.linkid = %s'%(tn, tn, a))
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

        # figure the order by clause
        orderby = []
        ordercols = []
        if sort[0] is not None and sort[1] is not None:
            direction, colname = sort
            if direction != '-':
                if colname == 'activity':
                    orderby.append('activity')
                    ordercols.append('max(%s__journal.date) as activity'%cn)
                    frum.append('%s__journal'%cn)
                    where.append('%s__journal.nodeid = _%s.id'%(cn, cn))
                elif colname == 'id':
                    orderby.append(colname)
                    ordercols.append(colname)
                else:
                    orderby.append('_'+colname)
                    ordercols.append('_'+colname)
            else:
                if colname == 'activity':
                    orderby.append('activity desc')
                    ordercols.append('max(%s__journal.date) as activity'%cn)
                    frum.append('%s__journal'%cn)
                    where.append('%s__journal.nodeid = _%s.id'%(cn, cn))
                elif colname == 'id':
                    orderby.append(colname+' desc')
                    ordercols.append(colname)
                else:
                    orderby.append('_'+colname+' desc')
                    ordercols.append('_'+colname)

        # figure the group by clause
        groupby = []
        groupcols = []
        if group[0] is not None and group[1] is not None:
            if group[0] != '-':
                groupby.append('_'+group[1])
                groupcols.append('_'+group[1])
            else:
                groupby.append('_'+group[1]+' desc')
                groupcols.append('_'+group[1])

        # construct the SQL
        frum = ','.join(frum)
        where = ' and '.join(where)
        cols = []
        if orderby:
            cols = cols + ordercols
            order = ' order by %s'%(','.join(orderby))
        else:
            order = ''
        if 0: #groupby:
            cols = cols + groupcols
            group = ' group by %s'%(','.join(groupby))
        else:
            group = ''
        if 'id' not in cols:
            cols.append('id')
        cols = ','.join(cols)
        sql = 'select %s from %s where %s%s%s'%(cols, frum, where, order,
            group)
        args = tuple(args)
        if __debug__:
            print >>hyperdb.DEBUG, 'filter', (self, sql, args)
        cursor = self.db.conn.cursor()
        cursor.execute(sql, args)
        l = cursor.fetchall()

        # return the IDs
        return [row[0] for row in l]

class Class(GadflyClass, Class):
    pass
class IssueClass(GadflyClass, IssueClass):
    pass
class FileClass(GadflyClass, FileClass):
    pass

