# $Id: back_sqlite.py,v 1.3 2002-09-19 02:37:41 richard Exp $
__doc__ = '''
See https://pysqlite.sourceforge.net/ for pysqlite info
'''
import base64, marshal
from roundup.backends.rdbms_common import *
import sqlite

class Database(Database):
    # char to use for positional arguments
    arg = '%s'

    def open_connection(self):
        # ensure files are group readable and writable
        os.umask(0002)
        db = os.path.join(self.config.DATABASE, 'db')
        self.conn = sqlite.connect(db=db)
        cursor = self.conn.cursor()
        try:
            self.database_schema = self.load_dbschema(cursor)
        except sqlite.DatabaseError, error:
            if str(error) != 'no such table: schema':
                raise
            self.database_schema = {}
            cursor = self.conn.cursor()
            cursor.execute('create table schema (schema varchar)')
            cursor.execute('create table ids (name varchar, num integer)')

    def __repr__(self):
        return '<roundlite 0x%x>'%id(self)

    def sql_fetchone(self, cursor):
        ''' Fetch a single row. If there's nothing to fetch, return None.
        '''
        return cursor.fetchone()

    def sql_commit(self):
        ''' Actually commit to the database.

            Ignore errors if there's nothing to commit.
        '''
        try:
            self.conn.commit()
        except sqlite.DatabaseError, error:
            if str(error) != 'cannot commit - no transaction is active':
                raise

    def save_dbschema(self, cursor, schema):
        ''' Save the schema definition that the database currently implements
        '''
        s = repr(self.database_schema)
        self.sql(cursor, 'insert into schema values (%s)', (s,))

    def load_dbschema(self, cursor):
        ''' Load the schema definition that the database currently implements
        '''
        cursor.execute('select schema from schema')
        return eval(cursor.fetchone()[0])

    def save_journal(self, cursor, classname, cols, nodeid, journaldate,
            journaltag, action, params):
        ''' Save the journal entry to the database
        '''
        # make the params db-friendly
        params = repr(params)
        entry = (nodeid, journaldate, journaltag, action, params)

        # do the insert
        a = self.arg
        sql = 'insert into %s__journal (%s) values (%s,%s,%s,%s,%s)'%(classname,
            cols, a, a, a, a, a)
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
            params = eval(params)
            res.append((nodeid, date.Date(date_stamp), user, action, params))
        return res

    def unserialise(self, classname, node):
        ''' Decode the marshalled node data

            SQLite stringifies _everything_... so we need to re-numberificate
            Booleans and Numbers.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'unserialise', classname, node
        properties = self.getclass(classname).getprops()
        d = {}
        for k, v in node.items():
            # if the property doesn't exist, or is the "retired" flag then
            # it won't be in the properties dict
            if not properties.has_key(k):
                d[k] = v
                continue

            # get the property spec
            prop = properties[k]

            if isinstance(prop, Date) and v is not None:
                d[k] = date.Date(v)
            elif isinstance(prop, Interval) and v is not None:
                d[k] = date.Interval(v)
            elif isinstance(prop, Password):
                p = password.Password()
                p.unpack(v)
                d[k] = p
            elif isinstance(prop, Boolean) and v is not None:
                d[k] = int(v)
            elif isinstance(prop, Number) and v is not None:
                # try int first, then assume it's a float
                try:
                    d[k] = int(v)
                except ValueError:
                    d[k] = float(v)
            else:
                d[k] = v
        return d

