from roundup.backends.rdbms_common import *
import MySQLdb
from MySQLdb.constants import ER

class Database(Database):
    arg = '%s'
    
    def open_connection(self):
        db = getattr(self.config, 'MYSQL_DATABASE')
        try:
            self.conn = MySQLdb.connect(*db)
        except MySQLdb.OperationalError, message:
            raise DatabaseError, message

        self.cursor = self.conn.cursor()
        try:
            self.database_schema = self.load_dbschema()
        except MySQLdb.ProgrammingError, message:
            if message[0] != ER.NO_SUCH_TABLE:
                raise DatabaseError, message
            self.database_schema = {}
            self.cursor.execute("CREATE TABLE schema (schema TEXT)")
            self.cursor.execute("CREATE TABLE ids (name varchar(255), num INT)")
    
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
        return eval(self.cursor.fetchone()[0])

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
        sql = 'CREATE TABLE `_%s` (%s)'%(spec.classname, scols)
        if __debug__:
          print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)
        return cols, mls

    def create_journal_table(self, spec):
        cols = ',' . join(['`%s` VARCHAR(255)'%x
          for x in 'nodeid date tag action params' . split()])
        sql  = 'CREATE TABLE `%s__journal` (%s)'%(spec.classname, cols)
        if __debug__:
            print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)

    def create_multilink_table(self, spec, ml):
        sql = '''CREATE TABLE `%s_%s` (linkid VARCHAR(255),
            nodeid VARCHAR(255))'''%(spec.classname, ml)
        if __debug__:
          print >>hyperdb.DEBUG, 'create_class', (self, sql)
        self.cursor.execute(sql)


