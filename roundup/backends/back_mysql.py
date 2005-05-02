#
# Copyright (c) 2003 Martynas Sklyzmantas, Andrey Lebedev <andrey@micro.lt>
#
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#

'''This module defines a backend implementation for MySQL.


How to implement AUTO_INCREMENT:

mysql> create table foo (num integer auto_increment primary key, name
varchar(255)) AUTO_INCREMENT=1 type=InnoDB;

ql> insert into foo (name) values ('foo5');
Query OK, 1 row affected (0.00 sec)

mysql> SELECT num FROM foo WHERE num IS NULL;
+-----+
| num |
+-----+
|   4 |
+-----+
1 row in set (0.00 sec)

mysql> SELECT num FROM foo WHERE num IS NULL;
Empty set (0.00 sec)

NOTE: we don't need an index on the id column if it's PRIMARY KEY

'''
__docformat__ = 'restructuredtext'

from roundup.backends.rdbms_common import *
from roundup.backends import rdbms_common
import MySQLdb
import os, shutil
from MySQLdb.constants import ER
import logging

def connection_dict(config, dbnamestr=None):
    d = rdbms_common.connection_dict(config, dbnamestr)
    if d.has_key('password'):
        d['passwd'] = d['password']
        del d['password']
    if d.has_key('port'):
        d['port'] = int(d['port'])
    return d

def db_nuke(config):
    """Clear all database contents and drop database itself"""
    if db_exists(config):
        kwargs = connection_dict(config)
        conn = MySQLdb.connect(**kwargs)
        try:
            conn.select_db(config.RDBMS_NAME)
        except:
            # no, it doesn't exist
            pass
        else:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            # stupid MySQL bug requires us to drop all the tables first
            for table in tables:
                command = 'DROP TABLE %s'%table[0]
                if __debug__:
                    logging.getLogger('hyperdb').debug(command)
                cursor.execute(command)
            command = "DROP DATABASE %s"%config.RDBMS_NAME
            logging.getLogger('hyperdb').info(command)
            cursor.execute(command)
            conn.commit()
        conn.close()

    if os.path.exists(config.DATABASE):
        shutil.rmtree(config.DATABASE)

def db_create(config):
    """Create the database."""
    kwargs = connection_dict(config)
    conn = MySQLdb.connect(**kwargs)
    cursor = conn.cursor()
    command = "CREATE DATABASE %s"%config.RDBMS_NAME
    logging.getLogger('hyperdb').info(command)
    cursor.execute(command)
    conn.commit()
    conn.close()

def db_exists(config):
    """Check if database already exists."""
    kwargs = connection_dict(config)
    conn = MySQLdb.connect(**kwargs)
    try:
        try:
            conn.select_db(config.RDBMS_NAME)
        except MySQLdb.OperationalError:
            return 0
    finally:
        conn.close()
    return 1


class Database(Database):
    arg = '%s'

    # used by some code to switch styles of query
    implements_intersect = 0

    # Backend for MySQL to use.
    # InnoDB is faster, but if you're running <4.0.16 then you'll need to
    # use BDB to pass all unit tests.
    mysql_backend = 'InnoDB'
    #mysql_backend = 'BDB'

    hyperdb_to_sql_datatypes = {
        hyperdb.String : 'VARCHAR(255)',
        hyperdb.Date   : 'DATETIME',
        hyperdb.Link   : 'INTEGER',
        hyperdb.Interval  : 'VARCHAR(255)',
        hyperdb.Password  : 'VARCHAR(255)',
        hyperdb.Boolean   : 'BOOL',
        hyperdb.Number    : 'REAL',
    }

    hyperdb_to_sql_value = {
        hyperdb.String : str,
        # no fractional seconds for MySQL
        hyperdb.Date   : lambda x: x.formal(sep=' '),
        hyperdb.Link   : int,
        hyperdb.Interval  : str,
        hyperdb.Password  : str,
        hyperdb.Boolean   : int,
        hyperdb.Number    : lambda x: x,
        hyperdb.Multilink : lambda x: x,    # used in journal marshalling
    }

    def sql_open_connection(self):
        kwargs = connection_dict(self.config, 'db')
        logging.getLogger('hyperdb').info('open database %r'%(kwargs['db'],))
        try:
            conn = MySQLdb.connect(**kwargs)
        except MySQLdb.OperationalError, message:
            raise DatabaseError, message
        cursor = conn.cursor()
        cursor.execute("SET AUTOCOMMIT=0")
        cursor.execute("START TRANSACTION")
        return (conn, cursor)

    def open_connection(self):
        # make sure the database actually exists
        if not db_exists(self.config):
            db_create(self.config)

        self.conn, self.cursor = self.sql_open_connection()

        try:
            self.load_dbschema()
        except MySQLdb.OperationalError, message:
            if message[0] != ER.NO_DB_ERROR:
                raise
        except MySQLdb.ProgrammingError, message:
            if message[0] != ER.NO_SUCH_TABLE:
                raise DatabaseError, message
            self.init_dbschema()
            self.sql("CREATE TABLE schema (schema TEXT) TYPE=%s"%
                self.mysql_backend)
            self.sql('''CREATE TABLE ids (name VARCHAR(255),
                num INTEGER) TYPE=%s'''%self.mysql_backend)
            self.sql('create index ids_name_idx on ids(name)')
            self.create_version_2_tables()

    def create_version_2_tables(self):
        # OTK store
        self.sql('''CREATE TABLE otks (otk_key VARCHAR(255),
            otk_value TEXT, otk_time FLOAT(20))
            TYPE=%s'''%self.mysql_backend)
        self.sql('CREATE INDEX otks_key_idx ON otks(otk_key)')

        # Sessions store
        self.sql('''CREATE TABLE sessions (session_key VARCHAR(255),
            session_time FLOAT(20), session_value TEXT)
            TYPE=%s'''%self.mysql_backend)
        self.sql('''CREATE INDEX sessions_key_idx ON
            sessions(session_key)''')

        # full-text indexing store
        self.sql('''CREATE TABLE __textids (_class VARCHAR(255),
            _itemid VARCHAR(255), _prop VARCHAR(255), _textid INT)
            TYPE=%s'''%self.mysql_backend)
        self.sql('''CREATE TABLE __words (_word VARCHAR(30),
            _textid INT) TYPE=%s'''%self.mysql_backend)
        self.sql('CREATE INDEX words_word_ids ON __words(_word)')
        sql = 'insert into ids (name, num) values (%s,%s)'%(self.arg, self.arg)
        self.sql(sql, ('__textids', 1))

    def add_new_columns_v2(self):
        '''While we're adding the actor column, we need to update the
        tables to have the correct datatypes.'''
        for klass in self.classes.values():
            cn = klass.classname
            properties = klass.getprops()
            old_spec = self.database_schema['tables'][cn]

            # figure the non-Multilink properties to copy over
            propnames = ['activity', 'creation', 'creator']

            # figure actions based on data type
            for name, s_prop in old_spec[1]:
                # s_prop is a repr() string of a hyperdb type object
                if s_prop.find('Multilink') == -1:
                    if properties.has_key(name):
                        propnames.append(name)
                    continue
                tn = '%s_%s'%(cn, name)

                if properties.has_key(name):
                    # grabe the current values
                    sql = 'select linkid, nodeid from %s'%tn
                    self.sql(sql)
                    rows = self.cursor.fetchall()

                # drop the old table
                self.drop_multilink_table_indexes(cn, name)
                sql = 'drop table %s'%tn
                self.sql(sql)

                if properties.has_key(name):
                    # re-create and populate the new table
                    self.create_multilink_table(klass, name)
                    sql = '''insert into %s (linkid, nodeid) values
                        (%s, %s)'''%(tn, self.arg, self.arg)
                    for linkid, nodeid in rows:
                        self.sql(sql, (int(linkid), int(nodeid)))

            # figure the column names to fetch
            fetch = ['_%s'%name for name in propnames]

            # select the data out of the old table
            fetch.append('id')
            fetch.append('__retired__')
            fetchcols = ','.join(fetch)
            sql = 'select %s from _%s'%(fetchcols, cn)
            self.sql(sql)

            # unserialise the old data
            olddata = []
            propnames = propnames + ['id', '__retired__']
            cols = []
            first = 1
            for entry in self.cursor.fetchall():
                l = []
                olddata.append(l)
                for i in range(len(propnames)):
                    name = propnames[i]
                    v = entry[i]

                    if name in ('id', '__retired__'):
                        if first:
                            cols.append(name)
                        l.append(int(v))
                        continue
                    if first:
                        cols.append('_' + name)
                    prop = properties[name]
                    if isinstance(prop, Date) and v is not None:
                        v = date.Date(v)
                    elif isinstance(prop, Interval) and v is not None:
                        v = date.Interval(v)
                    elif isinstance(prop, Password) and v is not None:
                        v = password.Password(encrypted=v)
                    elif (isinstance(prop, Boolean) or
                            isinstance(prop, Number)) and v is not None:
                        v = float(v)

                    # convert to new MySQL data type
                    prop = properties[name]
                    if v is not None:
                        e = self.hyperdb_to_sql_value[prop.__class__](v)
                    else:
                        e = None
                    l.append(e)

                    # Intervals store the seconds value too
                    if isinstance(prop, Interval):
                        if first:
                            cols.append('__' + name + '_int__')
                        if v is not None:
                            l.append(v.as_seconds())
                        else:
                            l.append(e)
                first = 0

            self.drop_class_table_indexes(cn, old_spec[0])

            # drop the old table
            self.sql('drop table _%s'%cn)

            # create the new table
            self.create_class_table(klass)

            # do the insert of the old data
            args = ','.join([self.arg for x in cols])
            cols = ','.join(cols)
            sql = 'insert into _%s (%s) values (%s)'%(cn, cols, args)
            for entry in olddata:
                self.sql(sql, tuple(entry))

            # now load up the old journal data to migrate it
            cols = ','.join('nodeid date tag action params'.split())
            sql = 'select %s from %s__journal'%(cols, cn)
            self.sql(sql)

            # data conversions
            olddata = []
            for nodeid, journaldate, journaltag, action, params in \
                    self.cursor.fetchall():
                #nodeid = int(nodeid)
                journaldate = date.Date(journaldate)
                #params = eval(params)
                olddata.append((nodeid, journaldate, journaltag, action,
                    params))

            # drop journal table and indexes
            self.drop_journal_table_indexes(cn)
            sql = 'drop table %s__journal'%cn
            self.sql(sql)

            # re-create journal table
            self.create_journal_table(klass)
            dc = self.hyperdb_to_sql_value[hyperdb.Date]
            for nodeid, journaldate, journaltag, action, params in olddata:
                self.save_journal(cn, cols, nodeid, dc(journaldate),
                    journaltag, action, params)

            # make sure the normal schema update code doesn't try to
            # change things
            self.database_schema['tables'][cn] = klass.schema()

    def fix_version_2_tables(self):
        # Convert journal date column to TIMESTAMP, params column to TEXT
        self._convert_journal_tables()

        # Convert all String properties to TEXT
        self._convert_string_properties()

    def __repr__(self):
        return '<myroundsql 0x%x>'%id(self)

    def sql_fetchone(self):
        return self.cursor.fetchone()

    def sql_fetchall(self):
        return self.cursor.fetchall()

    def sql_index_exists(self, table_name, index_name):
        self.sql('show index from %s'%table_name)
        for index in self.cursor.fetchall():
            if index[2] == index_name:
                return 1
        return 0

    def create_class_table(self, spec, create_sequence=1):
        cols, mls = self.determine_columns(spec.properties.items())

        # add on our special columns
        cols.append(('id', 'INTEGER PRIMARY KEY'))
        cols.append(('__retired__', 'INTEGER DEFAULT 0'))

        # create the base table
        scols = ','.join(['%s %s'%x for x in cols])
        sql = 'create table _%s (%s) type=%s'%(spec.classname, scols,
            self.mysql_backend)
        self.sql(sql)

        self.create_class_table_indexes(spec)
        return cols, mls

    def drop_class_table_indexes(self, cn, key):
        # drop the old table indexes first
        l = ['_%s_id_idx'%cn, '_%s_retired_idx'%cn]
        if key:
            l.append('_%s_%s_idx'%(cn, key))

        table_name = '_%s'%cn
        for index_name in l:
            if not self.sql_index_exists(table_name, index_name):
                continue
            index_sql = 'drop index %s on %s'%(index_name, table_name)
            self.sql(index_sql)

    def create_journal_table(self, spec):
        ''' create the journal table for a class given the spec and
            already-determined cols
        '''
        # journal table
        cols = ','.join(['%s varchar'%x
            for x in 'nodeid date tag action params'.split()])
        sql = '''create table %s__journal (
            nodeid integer, date datetime, tag varchar(255),
            action varchar(255), params text) type=%s'''%(
            spec.classname, self.mysql_backend)
        self.sql(sql)
        self.create_journal_table_indexes(spec)

    def drop_journal_table_indexes(self, classname):
        index_name = '%s_journ_idx'%classname
        if not self.sql_index_exists('%s__journal'%classname, index_name):
            return
        index_sql = 'drop index %s on %s__journal'%(index_name, classname)
        self.sql(index_sql)

    def create_multilink_table(self, spec, ml):
        sql = '''CREATE TABLE `%s_%s` (linkid VARCHAR(255),
            nodeid VARCHAR(255)) TYPE=%s'''%(spec.classname, ml,
                self.mysql_backend)
        self.sql(sql)
        self.create_multilink_table_indexes(spec, ml)

    def drop_multilink_table_indexes(self, classname, ml):
        l = [
            '%s_%s_l_idx'%(classname, ml),
            '%s_%s_n_idx'%(classname, ml)
        ]
        table_name = '%s_%s'%(classname, ml)
        for index_name in l:
            if not self.sql_index_exists(table_name, index_name):
                continue
            sql = 'drop index %s on %s'%(index_name, table_name)
            self.sql(sql)

    def drop_class_table_key_index(self, cn, key):
        table_name = '_%s'%cn
        index_name = '_%s_%s_idx'%(cn, key)
        if not self.sql_index_exists(table_name, index_name):
            return
        sql = 'drop index %s on %s'%(index_name, table_name)
        self.sql(sql)

    # old-skool id generation
    def newid(self, classname):
        ''' Generate a new id for the given class
        '''
        # get the next ID - "FOR UPDATE" will lock the row for us
        sql = 'select num from ids where name=%s FOR UPDATE'%self.arg
        self.sql(sql, (classname, ))
        newid = int(self.cursor.fetchone()[0])

        # update the counter
        sql = 'update ids set num=%s where name=%s'%(self.arg, self.arg)
        vals = (int(newid)+1, classname)
        self.sql(sql, vals)

        # return as string
        return str(newid)

    def setid(self, classname, setid):
        ''' Set the id counter: used during import of database

        We add one to make it behave like the seqeunces in postgres.
        '''
        sql = 'update ids set num=%s where name=%s'%(self.arg, self.arg)
        vals = (int(setid)+1, classname)
        self.sql(sql, vals)

    def clear(self):
        rdbms_common.Database.clear(self)

        # set the id counters to 0 (setid adds one) so we start at 1
        for cn in self.classes.keys():
            self.setid(cn, 0)

    def create_class(self, spec):
        rdbms_common.Database.create_class(self, spec)
        sql = 'insert into ids (name, num) values (%s, %s)'
        vals = (spec.classname, 1)
        self.sql(sql, vals)

    def sql_commit(self):
        ''' Actually commit to the database.
        '''
        logging.getLogger('hyperdb').info('commit')
        self.conn.commit()

        # open a new cursor for subsequent work
        self.cursor = self.conn.cursor()

        # make sure we're in a new transaction and not autocommitting
        self.sql("SET AUTOCOMMIT=0")
        self.sql("START TRANSACTION")

class MysqlClass:
    # we're overriding this method for ONE missing bit of functionality.
    # look for "I can't believe it's not a toy RDBMS" below
    def filter(self, search_matches, filterspec, sort=(None,None),
            group=(None,None)):
        '''Return a list of the ids of the active nodes in this class that
        match the 'filter' spec, sorted by the group spec and then the
        sort spec

        "filterspec" is {propname: value(s)}

        "sort" and "group" are (dir, prop) where dir is '+', '-' or None
        and prop is a prop name or None

        "search_matches" is {nodeid: marker} or None

        The filter must match all properties specificed - but if the
        property value to match is a list, any one of the values in the
        list may match for that property to match.
        '''
        # we can't match anything if search_matches is empty
        if search_matches == {}:
            return []

        if __debug__:
            start_t = time.time()

        cn = self.classname

        timezone = self.db.getUserTimezone()

        # vars to hold the components of the SQL statement
        frum = ['_'+cn] # FROM clauses
        loj = []        # LEFT OUTER JOIN clauses
        where = []      # WHERE clauses
        args = []       # *any* positional arguments
        a = self.db.arg

        # figure the WHERE clause from the filterspec
        props = self.getprops()
        mlfilt = 0      # are we joining with Multilink tables?
        for k, v in filterspec.items():
            propclass = props[k]
            # now do other where clause stuff
            if isinstance(propclass, Multilink):
                mlfilt = 1
                tn = '%s_%s'%(cn, k)
                if v in ('-1', ['-1']):
                    # only match rows that have count(linkid)=0 in the
                    # corresponding multilink table)

                    # "I can't believe it's not a toy RDBMS"
                    # see, even toy RDBMSes like gadfly and sqlite can do
                    # sub-selects...
                    self.db.sql('select nodeid from %s'%tn)
                    s = ','.join([x[0] for x in self.db.sql_fetchall()])

                    where.append('_%s.id not in (%s)'%(cn, s))
                elif isinstance(v, type([])):
                    frum.append(tn)
                    s = ','.join([a for x in v])
                    where.append('_%s.id=%s.nodeid and %s.linkid in (%s)'%(cn,
                        tn, tn, s))
                    args = args + v
                else:
                    frum.append(tn)
                    where.append('_%s.id=%s.nodeid and %s.linkid=%s'%(cn, tn,
                        tn, a))
                    args.append(v)
            elif k == 'id':
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s.%s in (%s)'%(cn, k, s))
                    args = args + v
                else:
                    where.append('_%s.%s=%s'%(cn, k, a))
                    args.append(v)
            elif isinstance(propclass, String):
                if not isinstance(v, type([])):
                    v = [v]

                # Quote the bits in the string that need it and then embed
                # in a "substring" search. Note - need to quote the '%' so
                # they make it through the python layer happily
                v = ['%%'+self.db.sql_stringquote(s)+'%%' for s in v]

                # now add to the where clause
                where.append('('
                    +' and '.join(["_%s._%s LIKE '%s'"%(cn, k, s) for s in v])
                    +')')
                # note: args are embedded in the query string now
            elif isinstance(propclass, Link):
                if isinstance(v, type([])):
                    d = {}
                    for entry in v:
                        if entry == '-1':
                            entry = None
                        d[entry] = entry
                    l = []
                    if d.has_key(None) or not d:
                        del d[None]
                        l.append('_%s._%s is NULL'%(cn, k))
                    if d:
                        v = d.keys()
                        s = ','.join([a for x in v])
                        l.append('(_%s._%s in (%s))'%(cn, k, s))
                        args = args + v
                    if l:
                        where.append('(' + ' or '.join(l) +')')
                else:
                    if v in ('-1', None):
                        v = None
                        where.append('_%s._%s is NULL'%(cn, k))
                    else:
                        where.append('_%s._%s=%s'%(cn, k, a))
                        args.append(v)
            elif isinstance(propclass, Date):
                dc = self.db.hyperdb_to_sql_value[hyperdb.Date]
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s._%s in (%s)'%(cn, k, s))
                    args = args + [dc(date.Date(x)) for x in v]
                else:
                    try:
                        # Try to filter on range of dates
                        date_rng = Range(v, date.Date, offset=timezone)
                        if date_rng.from_value:
                            where.append('_%s._%s >= %s'%(cn, k, a))
                            args.append(dc(date_rng.from_value))
                        if date_rng.to_value:
                            where.append('_%s._%s <= %s'%(cn, k, a))
                            args.append(dc(date_rng.to_value))
                    except ValueError:
                        # If range creation fails - ignore that search parameter
                        pass
            elif isinstance(propclass, Interval):
                # filter using the __<prop>_int__ column
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s.__%s_int__ in (%s)'%(cn, k, s))
                    args = args + [date.Interval(x).as_seconds() for x in v]
                else:
                    try:
                        # Try to filter on range of intervals
                        date_rng = Range(v, date.Interval)
                        if date_rng.from_value:
                            where.append('_%s.__%s_int__ >= %s'%(cn, k, a))
                            args.append(date_rng.from_value.as_seconds())
                        if date_rng.to_value:
                            where.append('_%s.__%s_int__ <= %s'%(cn, k, a))
                            args.append(date_rng.to_value.as_seconds())
                    except ValueError:
                        # If range creation fails - ignore that search parameter
                        pass
            else:
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s._%s in (%s)'%(cn, k, s))
                    args = args + v
                else:
                    where.append('_%s._%s=%s'%(cn, k, a))
                    args.append(v)

        # don't match retired nodes
        where.append('_%s.__retired__ <> 1'%cn)

        # add results of full text search
        if search_matches is not None:
            v = search_matches.keys()
            s = ','.join([a for x in v])
            where.append('_%s.id in (%s)'%(cn, s))
            args = args + v

        # sanity check: sorting *and* grouping on the same property?
        if group[1] == sort[1]:
            sort = (None, None)

        # "grouping" is just the first-order sorting in the SQL fetch
        orderby = []
        ordercols = []
        mlsort = []
        for sortby in group, sort:
            sdir, prop = sortby
            if sdir and prop:
                if isinstance(props[prop], Multilink):
                    mlsort.append(sortby)
                    continue
                elif isinstance(props[prop], Interval):
                    # use the int column for sorting
                    o = '__'+prop+'_int__'
                    ordercols.append(o)
                elif isinstance(props[prop], Link):
                    # determine whether the linked Class has an order property
                    lcn = props[prop].classname
                    link = self.db.classes[lcn]
                    o = '_%s._%s'%(cn, prop)
                    if link.getprops().has_key('order'):
                        tn = '_' + lcn
                        loj.append('LEFT OUTER JOIN %s on %s=%s.id'%(tn,
                            o, tn))
                        ordercols.append(tn + '._order')
                        o = tn + '._order'
                    else:
                        ordercols.append(o)
                elif prop == 'id':
                    o = '_%s.id'%cn
                else:
                    o = '_%s._%s'%(cn, prop)
                    ordercols.append(o)
                if sdir == '-':
                    o += ' desc'
                orderby.append(o)

        # construct the SQL
        frum = ','.join(frum)
        if where:
            where = ' where ' + (' and '.join(where))
        else:
            where = ''
        if mlfilt:
            # we're joining tables on the id, so we will get dupes if we
            # don't distinct()
            cols = ['distinct(_%s.id)'%cn]
        else:
            cols = ['_%s.id'%cn]
        if orderby:
            cols = cols + ordercols
            order = ' order by %s'%(','.join(orderby))
        else:
            order = ''
        cols = ','.join(cols)
        loj = ' '.join(loj)
        sql = 'select %s from %s %s %s%s'%(cols, frum, loj, where, order)
        args = tuple(args)
        self.db.sql(sql, args)
        l = self.db.cursor.fetchall()

        # return the IDs (the first column)
        # XXX numeric ids
        l = [str(row[0]) for row in l]

        if not mlsort:
            if __debug__:
                self.db.stats['filtering'] += (time.time() - start_t)
            return l

        # ergh. someone wants to sort by a multilink.
        r = []
        for id in l:
            m = []
            for ml in mlsort:
                m.append(self.get(id, ml[1]))
            r.append((id, m))
        i = 0
        for sortby in mlsort:
            def sortfun(a, b, dir=sortby[i], i=i):
                if dir == '-':
                    return cmp(b[1][i], a[1][i])
                else:
                    return cmp(a[1][i], b[1][i])
            r.sort(sortfun)
            i += 1
        r = [i[0] for i in r]

        if __debug__:
            self.db.stats['filtering'] += (time.time() - start_t)

        return r

class Class(MysqlClass, rdbms_common.Class):
    pass
class IssueClass(MysqlClass, rdbms_common.IssueClass):
    pass
class FileClass(MysqlClass, rdbms_common.FileClass):
    pass

# vim: set et sts=4 sw=4 :
