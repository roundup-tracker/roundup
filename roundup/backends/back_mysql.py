#$Id: back_mysql.py,v 1.74 2007-10-26 01:34:43 richard Exp $
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
varchar(255)) AUTO_INCREMENT=1 ENGINE=InnoDB;

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
                command = 'DROP TABLE `%s`'%table[0]
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
        hyperdb.String : 'TEXT',
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
            self.sql("CREATE TABLE `schema` (`schema` TEXT) ENGINE=%s"%
                self.mysql_backend)
            self.sql('''CREATE TABLE ids (name VARCHAR(255),
                num INTEGER) ENGINE=%s'''%self.mysql_backend)
            self.sql('create index ids_name_idx on ids(name)')
            self.create_version_2_tables()

    def load_dbschema(self):
        ''' Load the schema definition that the database currently implements
        '''
        self.cursor.execute('select `schema` from `schema`')
        schema = self.cursor.fetchone()
        if schema:
            self.database_schema = eval(schema[0])
        else:
            self.database_schema = {}

    def save_dbschema(self):
        ''' Save the schema definition that the database currently implements
        '''
        s = repr(self.database_schema)
        self.sql('delete from `schema`')
        self.sql('insert into `schema` values (%s)', (s,))

    def create_version_2_tables(self):
        # OTK store
        self.sql('''CREATE TABLE otks (otk_key VARCHAR(255),
            otk_value TEXT, otk_time FLOAT(20))
            ENGINE=%s'''%self.mysql_backend)
        self.sql('CREATE INDEX otks_key_idx ON otks(otk_key)')

        # Sessions store
        self.sql('''CREATE TABLE sessions (session_key VARCHAR(255),
            session_time FLOAT(20), session_value TEXT)
            ENGINE=%s'''%self.mysql_backend)
        self.sql('''CREATE INDEX sessions_key_idx ON
            sessions(session_key)''')

        # full-text indexing store
        self.sql('''CREATE TABLE __textids (_class VARCHAR(255),
            _itemid VARCHAR(255), _prop VARCHAR(255), _textid INT)
            ENGINE=%s'''%self.mysql_backend)
        self.sql('''CREATE TABLE __words (_word VARCHAR(30),
            _textid INT) ENGINE=%s'''%self.mysql_backend)
        self.sql('CREATE INDEX words_word_ids ON __words(_word)')
        self.sql('CREATE INDEX words_by_id ON __words (_textid)')
        self.sql('CREATE UNIQUE INDEX __textids_by_props ON '
                 '__textids (_class, _itemid, _prop)')
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
        sql = 'create table _%s (%s) ENGINE=%s'%(spec.classname, scols,
            self.mysql_backend)
        self.sql(sql)

        self.create_class_table_indexes(spec)
        return cols, mls

    def create_class_table_indexes(self, spec):
        ''' create the class table for the given spec
        '''
        # create __retired__ index
        index_sql2 = 'create index _%s_retired_idx on _%s(__retired__)'%(
                        spec.classname, spec.classname)
        self.sql(index_sql2)

        # create index for key property
        if spec.key:
            if isinstance(spec.properties[spec.key], String):
                idx = spec.key + '(255)'
            else:
                idx = spec.key
            index_sql3 = 'create index _%s_%s_idx on _%s(_%s)'%(
                        spec.classname, spec.key,
                        spec.classname, idx)
            self.sql(index_sql3)

        # TODO: create indexes on (selected?) Link property columns, as
        # they're more likely to be used for lookup

    def create_class_table_key_index(self, cn, key):
        ''' create the class table for the given spec
        '''
        prop = self.classes[cn].getprops()[key]
        if isinstance(prop, String):
            sql = 'create index _%s_%s_idx on _%s(_%s(255))'%(cn, key, cn, key)
        else:
            sql = 'create index _%s_%s_idx on _%s(_%s)'%(cn, key, cn, key)
        self.sql(sql)

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
            action varchar(255), params text) ENGINE=%s'''%(
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
            nodeid VARCHAR(255)) ENGINE=%s'''%(spec.classname, ml,
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

    def sql_commit(self, fail_ok=False):
        ''' Actually commit to the database.
        '''
        logging.getLogger('hyperdb').info('commit')

        # MySQL commits don't seem to ever fail, the latest update winning.
        # makes you wonder why they have transactions...
        self.conn.commit()

        # open a new cursor for subsequent work
        self.cursor = self.conn.cursor()

        # make sure we're in a new transaction and not autocommitting
        self.sql("SET AUTOCOMMIT=0")
        self.sql("START TRANSACTION")

    def sql_close(self):
        logging.getLogger('hyperdb').info('close')
        try:
            self.conn.close()
        except MySQLdb.ProgrammingError, message:
            if str(message) != 'closing a closed connection':
                raise

class MysqlClass:
    def _subselect(self, classname, multilink_table):
        ''' "I can't believe it's not a toy RDBMS"
           see, even toy RDBMSes like gadfly and sqlite can do sub-selects...
        '''
        self.db.sql('select nodeid from %s'%multilink_table)
        s = ','.join([x[0] for x in self.db.sql_fetchall()])
        return '_%s.id not in (%s)'%(classname, s)

class Class(MysqlClass, rdbms_common.Class):
    pass
class IssueClass(MysqlClass, rdbms_common.IssueClass):
    pass
class FileClass(MysqlClass, rdbms_common.FileClass):
    pass

# vim: set et sts=4 sw=4 :
