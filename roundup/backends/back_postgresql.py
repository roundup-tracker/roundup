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
import psycopg

from roundup import hyperdb, date
from roundup.backends import rdbms_common

def db_create(config):
    """Clear all database contents and drop database itself"""
    if __debug__:
        print >> hyperdb.DEBUG, '+++ create database +++'
    name = config.POSTGRESQL_DATABASE['database']
    n = 0
    while n < 10:
        cout,cin = popen2.popen4('createdb %s'%name)
        cin.close()
        response = cout.read().split('\n')[0]
        if response.find('FATAL') != -1:
            raise RuntimeError, response
        elif response.find('ERROR') != -1:
            if not response.find('is being accessed by other users') != -1:
                raise RuntimeError, response
            if __debug__:
                print >> hyperdb.DEBUG, '+++ SLEEPING +++'
            time.sleep(1)
            n += 1
            continue
        return
    raise RuntimeError, '10 attempts to create database failed'

def db_nuke(config, fail_ok=0):
    """Clear all database contents and drop database itself"""
    if __debug__:
        print >> hyperdb.DEBUG, '+++ nuke database +++'
    name = config.POSTGRESQL_DATABASE['database']
    n = 0
    if os.path.exists(config.DATABASE):
        shutil.rmtree(config.DATABASE)
    while n < 10:
        cout,cin = popen2.popen4('dropdb %s'%name)
        cin.close()
        response = cout.read().split('\n')[0]
        if response.endswith('does not exist') and fail_ok:
            return
        elif response.find('FATAL') != -1:
            raise RuntimeError, response
        elif response.find('ERROR') != -1:
            if not response.find('is being accessed by other users') != -1:
                raise RuntimeError, response
            if __debug__:
                print >> hyperdb.DEBUG, '+++ SLEEPING +++'
            time.sleep(1)
            n += 1
            continue
        return
    raise RuntimeError, '10 attempts to nuke database failed'

def db_exists(config):
    """Check if database already exists"""
    db = getattr(config, 'POSTGRESQL_DATABASE')
    try:
        conn = psycopg.connect(**db)
        conn.close()
        if __debug__:
            print >> hyperdb.DEBUG, '+++ database exists +++'
        return 1
    except:
        if __debug__:
            print >> hyperdb.DEBUG, '+++ no database +++'
        return 0

class Database(rdbms_common.Database):
    arg = '%s'

    def sql_open_connection(self):
        db = getattr(self.config, 'POSTGRESQL_DATABASE')
        try:
            conn = psycopg.connect(**db)
        except psycopg.OperationalError, message:
            raise hyperdb.DatabaseError, message

        cursor = conn.cursor()

        return (conn, cursor)

    def open_connection(self):
        if not db_exists(self.config):
            db_create(self.config)

        if __debug__:
            print >>hyperdb.DEBUG, '+++ open database connection +++'

        self.conn, self.cursor = self.sql_open_connection()

        try:
            self.load_dbschema()
        except:
            self.rollback()
            self.init_dbschema()
            self.sql("CREATE TABLE schema (schema TEXT)")
            self.sql("CREATE TABLE ids (name VARCHAR(255), num INT4)")
            self.sql("CREATE INDEX ids_name_idx ON ids(name)")
            self.create_version_2_tables()

    def create_version_2_tables(self):
        # OTK store
        self.cursor.execute('CREATE TABLE otks (otk_key VARCHAR(255), '
            'otk_value VARCHAR(255), otk_time FLOAT(20))')
        self.cursor.execute('CREATE INDEX otks_key_idx ON otks(otk_key)')

        # Sessions store
        self.cursor.execute('CREATE TABLE sessions (session_key VARCHAR(255), '
            'session_time FLOAT(20), session_value VARCHAR(255))')
        self.cursor.execute('CREATE INDEX sessions_key_idx ON '
            'sessions(session_key)')

        # full-text indexing store
        self.cursor.execute('CREATE TABLE _textids (_class VARCHAR(255), '
            '_itemid VARCHAR(255), _prop VARCHAR(255), _textid INT4) ')
        self.cursor.execute('CREATE TABLE _words (_word VARCHAR(30), '
            '_textid INT4)')
        self.cursor.execute('CREATE INDEX words_word_ids ON _words(_word)')
        sql = 'insert into ids (name, num) values (%s,%s)'%(self.arg, self.arg)
        self.cursor.execute(sql, ('_textids', 1))

    def add_actor_column(self):
        # update existing tables to have the new actor column
        tables = self.database_schema['tables']
        for name in tables.keys():
            self.cursor.execute('ALTER TABLE _%s add __actor '
                'VARCHAR(255)'%name)

    def __repr__(self):
        return '<roundpsycopgsql 0x%x>' % id(self)

    def sql_stringquote(self, value):
        ''' psycopg.QuotedString returns a "buffer" object with the
            single-quotes around it... '''
        return str(psycopg.QuotedString(str(value)))[1:-1]

    def sql_index_exists(self, table_name, index_name):
        sql = 'select count(*) from pg_indexes where ' \
            'tablename=%s and indexname=%s'%(self.arg, self.arg)
        self.cursor.execute(sql, (table_name, index_name))
        return self.cursor.fetchone()[0]

    def create_class_table(self, spec):
        cols, mls = self.determine_columns(spec.properties.items())
        cols.append('id')
        cols.append('__retired__')
        scols = ',' . join(['"%s" VARCHAR(255)'%x for x in cols])
        sql = 'CREATE TABLE "_%s" (%s)' % (spec.classname, scols)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class_table', (self, sql)
        self.cursor.execute(sql)
        self.create_class_table_indexes(spec)
        return cols, mls

    def create_journal_table(self, spec):
        cols = ',' . join(['"%s" VARCHAR(255)'%x
          for x in 'nodeid date tag action params' . split()])
        sql  = 'CREATE TABLE "%s__journal" (%s)'%(spec.classname, cols)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_journal_table', (self, sql)
        self.cursor.execute(sql)
        self.create_journal_table_indexes(spec)

    def create_multilink_table(self, spec, ml):
        sql = '''CREATE TABLE "%s_%s" (linkid VARCHAR(255),
            nodeid VARCHAR(255))'''%(spec.classname, ml)

        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)

        self.cursor.execute(sql)
        self.create_multilink_table_indexes(spec, ml)

class Class(rdbms_common.Class):
    pass
class IssueClass(rdbms_common.IssueClass):
    pass
class FileClass(rdbms_common.FileClass):
    pass

