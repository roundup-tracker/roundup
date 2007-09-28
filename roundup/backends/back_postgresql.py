#$Id: back_postgresql.py,v 1.43 2007-09-28 15:15:06 jpend Exp $
#
# Copyright (c) 2003 Martynas Sklyzmantas, Andrey Lebedev <andrey@micro.lt>
#
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
'''Postgresql backend via psycopg for Roundup.'''
__docformat__ = 'restructuredtext'

import os, shutil, popen2, time
try:
    import psycopg
    from psycopg import QuotedString
    from psycopg import ProgrammingError
except:
    from psycopg2 import psycopg1 as psycopg
    from psycopg2.extensions import QuotedString
    from psycopg2.psycopg1 import ProgrammingError
import logging

from roundup import hyperdb, date
from roundup.backends import rdbms_common
from roundup.backends import sessions_rdbms

def connection_dict(config, dbnamestr=None):
    ''' read_default_group is MySQL-specific, ignore it '''
    d = rdbms_common.connection_dict(config, dbnamestr)
    if d.has_key('read_default_group'):
        del d['read_default_group']
    if d.has_key('read_default_file'):
        del d['read_default_file']
    return d

def db_create(config):
    """Clear all database contents and drop database itself"""
    command = "CREATE DATABASE %s WITH ENCODING='UNICODE'"%config.RDBMS_NAME
    logging.getLogger('hyperdb').info(command)
    db_command(config, command)

def db_nuke(config, fail_ok=0):
    """Clear all database contents and drop database itself"""
    command = 'DROP DATABASE %s'% config.RDBMS_NAME
    logging.getLogger('hyperdb').info(command)
    db_command(config, command)

    if os.path.exists(config.DATABASE):
        shutil.rmtree(config.DATABASE)

def db_command(config, command):
    '''Perform some sort of database-level command. Retry 10 times if we
    fail by conflicting with another user.
    '''
    template1 = connection_dict(config)
    template1['database'] = 'template1'

    try:
        conn = psycopg.connect(**template1)
    except psycopg.OperationalError, message:
        raise hyperdb.DatabaseError, message

    conn.set_isolation_level(0)
    cursor = conn.cursor()
    try:
        for n in range(10):
            if pg_command(cursor, command):
                return
    finally:
        conn.close()
    raise RuntimeError, '10 attempts to create database failed'

def pg_command(cursor, command):
    '''Execute the postgresql command, which may be blocked by some other
    user connecting to the database, and return a true value if it succeeds.

    If there is a concurrent update, retry the command.
    '''
    try:
        cursor.execute(command)
    except psycopg.ProgrammingError, err:
        response = str(err).split('\n')[0]
        if response.find('FATAL') != -1:
            raise RuntimeError, response
        else:
            msgs = [
                'is being accessed by other users',
                'could not serialize access due to concurrent update',
            ]
            can_retry = 0
            for msg in msgs:
                if response.find(msg) == -1:
                    can_retry = 1
            if can_retry:
                time.sleep(1)
                return 0
            raise RuntimeError, response
    return 1

def db_exists(config):
    """Check if database already exists"""
    db = connection_dict(config, 'database')
    try:
        conn = psycopg.connect(**db)
        conn.close()
        return 1
    except:
        return 0

class Sessions(sessions_rdbms.Sessions):
    def set(self, *args, **kwargs):
        try:
            sessions_rdbms.Sessions.set(self, *args, **kwargs)
        except ProgrammingError, err:
            response = str(err).split('\n')[0]
            if -1 != response.find('ERROR') and \
               -1 != response.find('could not serialize access due to concurrent update'):
                # another client just updated, and we're running on
                # serializable isolation.
                # see http://www.postgresql.org/docs/7.4/interactive/transaction-iso.html
                self.db.rollback()

class Database(rdbms_common.Database):
    arg = '%s'

    # used by some code to switch styles of query
    implements_intersect = 1

    def getSessionManager(self):
        return Sessions(self)

    def sql_open_connection(self):
        db = connection_dict(self.config, 'database')
        logging.getLogger('hyperdb').info('open database %r'%db['database'])
        try:
            conn = psycopg.connect(**db)
        except psycopg.OperationalError, message:
            raise hyperdb.DatabaseError, message

        cursor = conn.cursor()

        return (conn, cursor)

    def open_connection(self):
        if not db_exists(self.config):
            db_create(self.config)

        self.conn, self.cursor = self.sql_open_connection()

        try:
            self.load_dbschema()
        except psycopg.ProgrammingError, message:
            if str(message).find('schema') == -1:
                raise
            self.rollback()
            self.init_dbschema()
            self.sql("CREATE TABLE schema (schema TEXT)")
            self.sql("CREATE TABLE dual (dummy integer)")
            self.sql("insert into dual values (1)")
            self.create_version_2_tables()

    def create_version_2_tables(self):
        # OTK store
        self.sql('''CREATE TABLE otks (otk_key VARCHAR(255),
            otk_value TEXT, otk_time REAL)''')
        self.sql('CREATE INDEX otks_key_idx ON otks(otk_key)')

        # Sessions store
        self.sql('''CREATE TABLE sessions (
            session_key VARCHAR(255), session_time REAL,
            session_value TEXT)''')
        self.sql('''CREATE INDEX sessions_key_idx ON
            sessions(session_key)''')

        # full-text indexing store
        self.sql('CREATE SEQUENCE ___textids_ids')
        self.sql('''CREATE TABLE __textids (
            _textid integer primary key, _class VARCHAR(255),
            _itemid VARCHAR(255), _prop VARCHAR(255))''')
        self.sql('''CREATE TABLE __words (_word VARCHAR(30),
            _textid integer)''')
        self.sql('CREATE INDEX words_word_idx ON __words(_word)')
        self.sql('CREATE INDEX words_by_id ON __words (_textid)')
        self.sql('CREATE UNIQUE INDEX __textids_by_props ON '
                 '__textids (_class, _itemid, _prop)')

    def fix_version_2_tables(self):
        # Convert journal date column to TIMESTAMP, params column to TEXT
        self._convert_journal_tables()

        # Convert all String properties to TEXT
        self._convert_string_properties()

        # convert session / OTK *_time columns to REAL
        for name in ('otk', 'session'):
            self.sql('drop index %ss_key_idx'%name)
            self.sql('drop table %ss'%name)
            self.sql('''CREATE TABLE %ss (%s_key VARCHAR(255),
                %s_value VARCHAR(255), %s_time REAL)'''%(name, name, name,
                name))
            self.sql('CREATE INDEX %ss_key_idx ON %ss(%s_key)'%(name, name,
                name))

    def fix_version_3_tables(self):
        rdbms_common.Database.fix_version_3_tables(self)
        self.sql('''CREATE INDEX words_both_idx ON public.__words
            USING btree (_word, _textid)''')

    def add_actor_column(self):
        # update existing tables to have the new actor column
        tables = self.database_schema['tables']
        for name in tables.keys():
            self.sql('ALTER TABLE _%s add __actor VARCHAR(255)'%name)

    def __repr__(self):
        return '<roundpsycopgsql 0x%x>' % id(self)

    def sql_commit(self, fail_ok=False):
        ''' Actually commit to the database.
        '''
        logging.getLogger('hyperdb').info('commit')

        try:
            self.conn.commit()
        except psycopg.ProgrammingError, message:
            # we've been instructed that this commit is allowed to fail
            if fail_ok and str(message).endswith('could not serialize '
                    'access due to concurrent update'):
                logging.getLogger('hyperdb').info('commit FAILED, but fail_ok')
            else:
                raise

        # open a new cursor for subsequent work
        self.cursor = self.conn.cursor()

    def sql_stringquote(self, value):
        ''' psycopg.QuotedString returns a "buffer" object with the
            single-quotes around it... '''
        return str(QuotedString(str(value)))[1:-1]

    def sql_index_exists(self, table_name, index_name):
        sql = 'select count(*) from pg_indexes where ' \
            'tablename=%s and indexname=%s'%(self.arg, self.arg)
        self.sql(sql, (table_name, index_name))
        return self.cursor.fetchone()[0]

    def create_class_table(self, spec, create_sequence=1):
        if create_sequence:
            sql = 'CREATE SEQUENCE _%s_ids'%spec.classname
            self.sql(sql)

        return rdbms_common.Database.create_class_table(self, spec)

    def drop_class_table(self, cn):
        sql = 'drop table _%s'%cn
        self.sql(sql)

        sql = 'drop sequence _%s_ids'%cn
        self.sql(sql)

    def newid(self, classname):
        sql = "select nextval('_%s_ids') from dual"%classname
        self.sql(sql)
        return self.cursor.fetchone()[0]

    def setid(self, classname, setid):
        sql = "select setval('_%s_ids', %s) from dual"%(classname, int(setid))
        self.sql(sql)

    def clear(self):
        rdbms_common.Database.clear(self)

        # reset the sequences
        for cn in self.classes.keys():
            self.cursor.execute('DROP SEQUENCE _%s_ids'%cn)
            self.cursor.execute('CREATE SEQUENCE _%s_ids'%cn)

class PostgresqlClass:
    order_by_null_values = '(%s is not NULL)'

class Class(PostgresqlClass, rdbms_common.Class):
    pass
class IssueClass(PostgresqlClass, rdbms_common.IssueClass):
    pass
class FileClass(PostgresqlClass, rdbms_common.FileClass):
    pass

# vim: set et sts=4 sw=4 :
