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

from roundup import date, hyperdb, password
from roundup.backends import rdbms_common
import MySQLdb
import os, shutil, sys
from MySQLdb.constants import ER
import logging

isolation_levels = \
    { 'read uncommitted': 'READ UNCOMMITTED'
    , 'read committed': 'READ COMMITTED'
    , 'repeatable read': 'REPEATABLE READ'
    , 'serializable': 'SERIALIZABLE'
    }

def connection_dict(config, dbnamestr=None):
    d = rdbms_common.connection_dict(config, dbnamestr)
    if 'password' in d:
        d['passwd'] = d['password']
        del d['password']
    if 'port' in d:
        d['port'] = int(d['port'])
    charset = config.RDBMS_MYSQL_CHARSET
    if charset != 'default':
        d['charset'] = charset
    return d

def db_nuke(config):
    """Clear all database contents and drop database itself"""
    if db_exists(config):
        kwargs = connection_dict(config)
        conn = MySQLdb.connect(**kwargs)
        try:
            conn.select_db(config.RDBMS_NAME)
        except MySQLdb.Error:
            # no, it doesn't exist
            pass
        else:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            # stupid MySQL bug requires us to drop all the tables first
            for table in tables:
                command = 'DROP TABLE `%s`'%table[0]
                logging.debug(command)
                cursor.execute(command)
            command = "DROP DATABASE %s"%config.RDBMS_NAME
            logging.info(command)
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
    if sys.version_info[0] > 2:
        command += ' CHARACTER SET utf8'
    logging.info(command)
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


class Database(rdbms_common.Database):
    """ Mysql DB backend implementation

    attributes:
      dbtype:
        holds the value for the type of db. It is used by indexer to
        identify the database type so it can import the correct indexer
        module when using native text search mode.
    """

    arg = '%s'

    dbtype = "mysql"

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
        hyperdb.Integer   : 'INTEGER',
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
        hyperdb.Integer   : int,
        hyperdb.Multilink : lambda x: x,    # used in journal marshalling
    }

    def sql_open_connection(self):
        kwargs = connection_dict(self.config, 'db')
        self.log_info('open database %r'%(kwargs['db'],))
        try:
            conn = MySQLdb.connect(**kwargs)
        except MySQLdb.OperationalError as message:
            raise hyperdb.DatabaseError(message)
        cursor = conn.cursor()
        cursor.execute("SET AUTOCOMMIT=0")
        lvl = isolation_levels [self.config.RDBMS_ISOLATION_LEVEL]
        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL %s" % lvl)
        cursor.execute("START TRANSACTION")
        return (conn, cursor)

    def open_connection(self):
        # make sure the database actually exists
        if not db_exists(self.config):
            db_create(self.config)

        self.conn, self.cursor = self.sql_open_connection()

        try:
            self.load_dbschema()
        except MySQLdb.OperationalError as message:
            if message.args[0] != ER.NO_DB_ERROR:
                raise
        except MySQLdb.ProgrammingError as message:
            if message.args[0] != ER.NO_SUCH_TABLE:
                raise hyperdb.DatabaseError(message)
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
            # bandit - schema is trusted
            self.database_schema = eval(schema[0])  # nosec
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
                    if name in properties:
                        propnames.append(name)
                    continue
                tn = '%s_%s'%(cn, name)

                if name in properties:
                    # grabe the current values
                    sql = 'select linkid, nodeid from %s'%tn
                    self.sql(sql)
                    rows = self.cursor.fetchall()

                # drop the old table
                self.drop_multilink_table_indexes(cn, name)
                sql = 'drop table %s'%tn
                self.sql(sql)

                if name in properties:
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
                    if isinstance(prop, hyperdb.Date) and v is not None:
                        v = date.Date(v)
                    elif isinstance(prop, hyperdb.Interval) and v is not None:
                        v = date.Interval(v)
                    elif isinstance(prop, hyperdb.Password) and v is not None:
                        v = password.Password(encrypted=v)
                    elif isinstance(prop, hyperdb.Integer) and v is not None:
                        v = int(v)
                    elif (isinstance(prop, hyperdb.Boolean) or
                            isinstance(prop, hyperdb.Number)) and v is not None:
                        v = float(v)

                    # convert to new MySQL data type
                    prop = properties[name]
                    if v is not None:
                        e = self.to_sql_value(prop.__class__)(v)
                    else:
                        e = None
                    l.append(e)

                    # Intervals store the seconds value too
                    if isinstance(prop, hyperdb.Interval):
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
            dc = self.to_sql_value(hyperdb.Date)
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

    def fix_version_5_tables(self):
        # A bug caused the _<class>_key_retired_idx to be missing
        # unless the database was upgraded from version 4 to 5.
        # If it was created at version 5, the index is missing.
        # The user class is always present and has a key.
        # Check it for the index. If missing, add index to all
        # classes by rerunning self.fix_version_4_tables().

        # if this fails abort. Probably means no user class
        # so we should't be doing anything.
        if not self.sql_index_exists("_user", "_user_key_retired_idx"):
            self.fix_version_4_tables()
        else:
            self.log_info('No changes needed.')

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
            if isinstance(spec.properties[spec.key], hyperdb.String):
                idx = spec.key + '(255)'
            else:
                idx = spec.key
            index_sql3 = 'create index _%s_%s_idx on _%s(_%s)'%(
                        spec.classname, spec.key,
                        spec.classname, idx)
            self.sql(index_sql3)

            # and the unique index for key / retired(id)
            self.add_class_key_required_unique_constraint(spec.classname,
                                                          spec.key)

        # TODO: create indexes on (selected?) Link property columns, as
        # they're more likely to be used for lookup

    def add_class_key_required_unique_constraint(self, cn, key):
        # mysql requires sizes on TEXT indexes
        prop = self.classes[cn].getprops()[key]
        if isinstance(prop, hyperdb.String):
            sql = '''create unique index _%s_key_retired_idx
                on _%s(__retired__, _%s(255))'''%(cn, cn, key)
        else:
            sql = '''create unique index _%s_key_retired_idx
                on _%s(__retired__, _%s)'''%(cn, cn, key)
        self.sql(sql)

    def create_class_table_key_index(self, cn, key):
        # mysql requires sizes on TEXT indexes
        prop = self.classes[cn].getprops()[key]
        if isinstance(prop, hyperdb.String):
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

        # and now the retired unique index too
        index_name = '_%s_key_retired_idx' % cn
        if self.sql_index_exists(table_name, index_name):
            sql = 'drop index %s on _%s'%(index_name, cn)
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
        self.log_info('commit')

        # MySQL commits don't seem to ever fail, the latest update winning.
        # makes you wonder why they have transactions...
        self.conn.commit()

        # open a new cursor for subsequent work
        self.cursor = self.conn.cursor()

        # make sure we're in a new transaction and not autocommitting
        self.sql("SET AUTOCOMMIT=0")
        self.sql("START TRANSACTION")

    def sql_close(self):
        self.log_info('close')
        try:
            self.conn.close()
        # issue2551025: with revision 1.3.14 of mysqlclient.
        # It looks like you can get an OperationalError 2006
        # raised for closing a closed handle.
        except MySQLdb.OperationalError as message:
            if str(message) != "(2006, '')":  # close connection
                raise
        except MySQLdb.ProgrammingError as message:
            if str(message) != 'closing a closed connection':
                raise

class MysqlClass:
    case_sensitive_equal = 'COLLATE utf8_bin ='

    # TODO: AFAIK its version dependent for MySQL
    supports_subselects = False

    def _subselect(self, proptree):
        ''' "I can't believe it's not a toy RDBMS"
           see, even toy RDBMSes like gadfly and sqlite can do sub-selects...
        '''
        classname       = proptree.parent.classname
        multilink_table = proptree.propclass.table_name
        nodeid_name     = proptree.propclass.nodeid_name
        linkid_name     = proptree.propclass.linkid_name

        w = ''
        if proptree.need_retired:
            w = ' where %s.__retired__=0'%(multilink_table)
        if proptree.need_child_retired:
            tn1 = multilink_table
            tn2 = '_' + proptree.classname
            w = ', %s where %s.%s=%s.id and %s.__retired__=0'%(tn2, tn1,
                linkid_name, tn2, tn2)
        self.db.sql('select %s from %s%s'%(nodeid_name, multilink_table, w))
        s = ','.join([str(x[0]) for x in self.db.sql_fetchall()])
        return '_%s.id not in (%s)'%(classname, s)

    def create_inner(self, **propvalues):
        try:
            return rdbms_common.Class.create_inner(self, **propvalues)
        except MySQLdb.IntegrityError as e:
            self._handle_integrity_error(e, propvalues)

    def set_inner(self, nodeid, **propvalues):
        try:
            return rdbms_common.Class.set_inner(self, nodeid,
                                                **propvalues)
        except MySQLdb.IntegrityError as e:
            self._handle_integrity_error(e, propvalues)

    def _handle_integrity_error(self, e, propvalues):
        ''' Handle a MySQL IntegrityError.

        If the error is recognized, then it may be converted into an
        alternative exception.  Otherwise, it is raised unchanged from
        this function.'''

        # There are checks in create_inner/set_inner to see if a node
        # is being created with the same key as an existing node.
        # But, there is a race condition -- we may pass those checks,
        # only to find out that a parallel session has created the
        # node by by the time we actually issue the SQL command to
        # create the node.  Fortunately, MySQL gives us a unique error
        # code for this situation, so we can detect it here and handle
        # it appropriately.
        # 
        # The details of the race condition are as follows, where
        # "X" is a classname, and the term "thread" is meant to
        # refer generically to both threads and processes:
        #
        # Thread A                    Thread B
        # --------                    --------
        #                             read table for X
        # create new X object
        # commit
        #                             create new X object
        #
        # In Thread B, the check in create_inner does not notice that
        # the new X object is a duplicate of that committed in Thread
        # A because MySQL's default "consistent nonlocking read"
        # behavior means that Thread B sees a snapshot of the database
        # at the point at which its transaction began -- which was
        # before Thread A created the object.  However, the attempt
        # to *write* to the table for X, creating a duplicate entry,
        # triggers an error at the point of the write.
        #
        # If both A and B's transaction begins with creating a new X
        # object, then this bug cannot occur because creating the
        # object requires getting a new ID, and newid() locks the id
        # table until the transaction is committed or rolledback.  So,
        # B will block until A's commit is complete, and will not
        # actually get its snapshot until A's transaction completes.
        # But, if the transaction has begun prior to calling newid,
        # then the snapshot has already been established.
        if e[0] == ER.DUP_ENTRY:
            key = propvalues[self.key]
            raise ValueError('node with key "%s" exists' % key)
        # We don't know what this exception is; reraise it.
        raise
        

class Class(MysqlClass, rdbms_common.Class):
    pass
class IssueClass(MysqlClass, rdbms_common.IssueClass):
    pass
class FileClass(MysqlClass, rdbms_common.FileClass):
    pass

# vim: set et sts=4 sw=4 :
