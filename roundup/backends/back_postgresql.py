#
# Copyright (c) 2003 Martynas Sklyzmantas, Andrey Lebedev <andrey@micro.lt>
#
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# psycopg backend for roundup
#

from roundup import hyperdb, date
from roundup.backends import rdbms_common
import psycopg
import os, shutil, popen2

class Database(rdbms_common.Database):
    arg = '%s'

    def sql_open_connection(self):
        db = getattr(self.config, 'POSTGRESQL_DATABASE')
        try:
            self.conn = psycopg.connect(**db)
        except psycopg.OperationalError, message:
            raise DatabaseError, message

        self.cursor = self.conn.cursor()

        try:
            self.database_schema = self.load_dbschema()
        except:
            self.rollback()
            self.database_schema = {}
            self.sql("CREATE TABLE schema (schema TEXT)")
            self.sql("CREATE TABLE ids (name VARCHAR(255), num INT4)")

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
        scols = ',' . join(['"%s" VARCHAR(255)' % x for x in cols])
        sql = 'CREATE TABLE "_%s" (%s)' % (spec.classname, scols)

        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)

        self.cursor.execute(sql)
        return cols, mls

    def create_journal_table(self, spec):
        cols = ',' . join(['"%s" VARCHAR(255)' % x
                           for x in 'nodeid date tag action params' . split()])
        sql  = 'CREATE TABLE "%s__journal" (%s)'%(spec.classname, cols)
        
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)

        self.cursor.execute(sql)

    def create_multilink_table(self, spec, ml):
        sql = '''CREATE TABLE "%s_%s" (linkid VARCHAR(255),
                   nodeid VARCHAR(255))''' % (spec.classname, ml)

        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)

        self.cursor.execute(sql)

class Class(rdbms_common.Class):
    pass
class IssueClass(rdbms_common.IssueClass):
    pass
class FileClass(rdbms_common.FileClass):
    pass

