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

# Database maintenance functions
def db_nuke(config):
    """Clear all database contents and drop database itself"""
    db = Database(config, 'admin')
    try:
        db.sql_commit()
        db.sql("DROP DATABASE %s" % config.MYSQL_DBNAME)
        db.sql("CREATE DATABASE %s" % config.MYSQL_DBNAME)
    finally:
        db.close()
    if os.path.exists(config.DATABASE):
        shutil.rmtree(config.DATABASE)

def db_exists(config):
    """Check if database already exists"""
    # Yes, this is a hack, but we must must open connection without
    # selecting a database to prevent creation of some tables
    config.MYSQL_DATABASE = (config.MYSQL_DBHOST, config.MYSQL_DBUSER,
        config.MYSQL_DBPASSWORD)        
    db = Database(config, 'admin')
    try:
        db.conn.select_db(config.MYSQL_DBNAME)
        config.MYSQL_DATABASE = (config.MYSQL_DBHOST, config.MYSQL_DBUSER,
            config.MYSQL_DBPASSWORD, config.MYSQL_DBNAME)
        db.sql("SHOW TABLES")
        tables = db.sql_fetchall()
    finally:
        db.close()
    if tables or os.path.exists(config.DATABASE):
        return 1
    return 0        

class Database(Database):
    arg = '%s'

    # backend for MySQL to use
    mysql_backend = 'InnoDB'
    #mysql_backend = 'BDB'    # much slower, only use if you have no choice
    
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
            self.sql("CREATE TABLE schema (schema TEXT) TYPE=%s"%
                self.mysql_backend)
            # TODO: use AUTO_INCREMENT for generating ids:
            #       http://www.mysql.com/doc/en/CREATE_TABLE.html
            self.sql("CREATE TABLE ids (name varchar(255), num INT) TYPE=%s"%
                self.mysql_backend)
            self.sql("CREATE INDEX ids_name_idx on ids(name)")

    def close(self):
        self.conn.close()

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
        sql = 'CREATE TABLE `_%s` (%s) TYPE=%s'%(spec.classname, scols,
            self.mysql_backend)
        if __debug__:
          print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)
        return cols, mls

    def create_journal_table(self, spec):
        cols = ',' . join(['`%s` VARCHAR(255)'%x
          for x in 'nodeid date tag action params' . split()])
        sql  = 'CREATE TABLE `%s__journal` (%s) TYPE=%s'%(spec.classname,
            cols, self.mysql_backend)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)

    def create_multilink_table(self, spec, ml):
        sql = '''CREATE TABLE `%s_%s` (linkid VARCHAR(255),
            nodeid VARCHAR(255)) TYPE=%s'''%(spec.classname, ml,
                self.mysql_backend)
        if __debug__:
          print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)

class MysqlClass:
    # we're overriding this method for ONE missing bit of functionality.
    # look for "I can't believe it's not a toy RDBMS" below
    def filter(self, search_matches, filterspec, sort=(None,None),
            group=(None,None)):
        ''' Return a list of the ids of the active nodes in this class that
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

                    # "I can't believe it's not a toy RDBMS"
                    # see, even toy RDBMSes like gadfly and sqlite can do
                    # sub-selects...
                    self.db.sql('select nodeid from %s'%tn)
                    s = ','.join([x[0] for x in self.db.sql_fetchall()])

                    where.append('id not in (%s)'%s)
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
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s in (%s)'%(k, s))
                    args = args + [date.Date(x).serialise() for x in v]
                else:
                    try:
                        # Try to filter on range of dates
                        date_rng = Range(v, date.Date, offset=timezone)
                        if (date_rng.from_value):
                            where.append('_%s >= %s'%(k, a))                            
                            args.append(date_rng.from_value.serialise())
                        if (date_rng.to_value):
                            where.append('_%s <= %s'%(k, a))
                            args.append(date_rng.to_value.serialise())
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
                        if (date_rng.from_value):
                            where.append('_%s >= %s'%(k, a))
                            args.append(date_rng.from_value.serialise())
                        if (date_rng.to_value):
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
        self.db.cursor.execute(sql, args)
        l = self.db.cursor.fetchall()

        # return the IDs (the first column)
        return [row[0] for row in l]

class Class(MysqlClass, rdbms_common.Class):
    pass
class IssueClass(MysqlClass, rdbms_common.IssueClass):
    pass
class FileClass(MysqlClass, rdbms_common.FileClass):
    pass

#vim: set et
