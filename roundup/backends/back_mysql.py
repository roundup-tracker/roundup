#
# Copyright (c) 2003 Martynas Sklyzmantas, Andrey Lebedev <andrey@micro.lt>
#
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# Mysql backend for roundup
#

from roundup.backends.rdbms_common import *
from roundup.backends import rdbms_common
import MySQLdb
import os, shutil
from MySQLdb.constants import ER

class Maintenance:
    """ Database maintenance functions """
    def db_nuke(self, config):
        """Clear all database contents and drop database itself"""
        db = Database(config, 'admin')
        db.sql("DROP DATABASE %s" % config.MYSQL_DBNAME)
        db.sql("CREATE DATABASE %s" % config.MYSQL_DBNAME)
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        
    def db_exists(self, config):
        """Check if database already exists"""
        # Yes, this is a hack, but we must must open connection without
        # selecting a database to prevent creation of some tables
        config.MYSQL_DATABASE = (config.MYSQL_DBHOST, config.MYSQL_DBUSER, config.MYSQL_DBPASSWORD)        
        db = Database(config, 'admin')
        db.conn.select_db(config.MYSQL_DBNAME)
        config.MYSQL_DATABASE = (config.MYSQL_DBHOST, config.MYSQL_DBUSER, config.MYSQL_DBPASSWORD, config.MYSQL_DBNAME)
        db.sql("SHOW TABLES")
        tables = db.sql_fetchall()
        if tables or os.path.exists(config.DATABASE):
            return 1
        return 0        

class Database(Database):
    arg = '%s'
    
    def open_connection(self):
        db = getattr(self.config, 'MYSQL_DATABASE')
        try:
            self.conn = MySQLdb.connect(*db)
        except MySQLdb.OperationalError, message:
            raise DatabaseError, message

        self.cursor = self.conn.cursor()
        # start transaction
        self.sql("SET AUTOCOMMIT=0")
        self.sql("BEGIN")
        try:
            self.database_schema = self.load_dbschema()
        except MySQLdb.OperationalError, message:
            if message[0] != ER.NO_DB_ERROR:
                raise
        except MySQLdb.ProgrammingError, message:
            if message[0] != ER.NO_SUCH_TABLE:
                raise DatabaseError, message
            self.database_schema = {}
            self.sql("CREATE TABLE schema (schema TEXT) TYPE=BDB")
            self.sql("CREATE TABLE ids (name varchar(255), num INT) TYPE=BDB")
            self.sql("CREATE INDEX ids_name_idx on ids(name)")
    
    def close(self):
        try:
            self.conn.close()
        except MySQLdb.OperationalError, message:
         raise 

    def __repr__(self):
        return '<myroundsql 0x%x>'%id(self)

    def sql_fetchone(self):
        return self.cursor.fetchone()

    def sql_fetchall(self):
        return self.cursor.fetchall()
    
    def save_dbschema(self, schema):
        s = repr(self.database_schema)
        self.sql('INSERT INTO schema VALUES (%s)', (s,))
    
    def load_dbschema(self):
        self.cursor.execute('SELECT schema FROM schema')
        schema = self.cursor.fetchone()
        if schema:
            return eval(schema[0])
        return None

    def save_journal(self, classname, cols, nodeid, journaldate,
                journaltag, action, params):
        params = repr(params)
        entry = (nodeid, journaldate, journaltag, action, params)

        a = self.arg
        sql = 'insert into %s__journal (%s) values (%s,%s,%s,%s,%s)'%(classname,
                cols, a, a, a, a, a)
        if __debug__:
          print >>hyperdb.DEBUG, 'addjournal', (self, sql, entry)
        self.cursor.execute(sql, entry)

    def load_journal(self, classname, cols, nodeid):
        sql = 'select %s from %s__journal where nodeid=%s'%(cols, classname,
                self.arg)
        if __debug__:
            print >>hyperdb.DEBUG, 'getjournal', (self, sql, nodeid)
        self.cursor.execute(sql, (nodeid,))
        res = []
        for nodeid, date_stamp, user, action, params in self.cursor.fetchall():
          params = eval(params)
          res.append((nodeid, date.Date(date_stamp), user, action, params))
        return res

    def create_class_table(self, spec):
        cols, mls = self.determine_columns(spec.properties.items())
        cols.append('id')
        cols.append('__retired__')
        scols = ',' . join(['`%s` VARCHAR(255)'%x for x in cols])
        sql = 'CREATE TABLE `_%s` (%s) TYPE=BDB'%(spec.classname, scols)
        if __debug__:
          print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)
        return cols, mls

    def create_journal_table(self, spec):
        cols = ',' . join(['`%s` VARCHAR(255)'%x
          for x in 'nodeid date tag action params' . split()])
        sql  = 'CREATE TABLE `%s__journal` (%s) TYPE=BDB'%(spec.classname, cols)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)

    def create_multilink_table(self, spec, ml):
        sql = '''CREATE TABLE `%s_%s` (linkid VARCHAR(255),
            nodeid VARCHAR(255)) TYPE=BDB'''%(spec.classname, ml)
        if __debug__:
          print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)

    # Static methods
    nuke = Maintenance().db_nuke
    exists = Maintenance().db_exists

class MysqlClass:
    def find(self, **propspec):
        '''Get the ids of nodes in this class which link to the given nodes.

        Since MySQL < 4.0.0 does not support unions, so we overrideg this
        method without using this keyword

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
        l = []
        where = []
        allvalues = ()
        a = self.db.arg
        for prop, values in propspec:
            if not isinstance(props[prop], hyperdb.Link):
                continue
            if type(values) is type(''):
                allvalues += (values,)
                where.append('_%s = %s'%(prop, a))
            else:
                allvalues += tuple(values.keys())
                where.append('_%s in (%s)'%(prop, ','.join([a]*len(values))))
        tables = []
        if where:
            self.db.sql('select id as nodeid from _%s where %s' % (self.classname, ' and '.join(where)), allvalues)
            l += [x[0] for x in self.db.sql_fetchall()]

        # now multilinks
        for prop, values in propspec:
            vals = ()
            if not isinstance(props[prop], hyperdb.Multilink):
                continue
            if type(values) is type(''):
                vals = (values,)
                s = a
            else:
                vals = tuple(values.keys())
                s = ','.join([a]*len(values))
            query = 'select nodeid from %s_%s where linkid in (%s)'%(
                self.classname, prop, s)
            self.db.sql(query, vals)
            l += [x[0] for x in self.db.sql_fetchall()]
        if __debug__:
            print >>hyperdb.DEBUG, 'find ... ', l

        # Remove duplicated ids
        d = {}
        for k in l:
            d[k] = 1
        return d.keys()

        return l

class Class(MysqlClass, rdbms_common.Class):
    pass
class IssueClass(MysqlClass, rdbms_common.IssueClass):
    pass
class FileClass(MysqlClass, rdbms_common.FileClass):
    pass

#vim: set et
