# $Id: back_sqlite.py,v 1.9 2003-03-06 06:03:51 richard Exp $
__doc__ = '''
See https://pysqlite.sourceforge.net/ for pysqlite info
'''
import base64, marshal
from roundup.backends.rdbms_common import *
from roundup.backends import locking
import sqlite

class Database(Database):
    # char to use for positional arguments
    arg = '%s'

    def open_connection(self):
        # ensure files are group readable and writable
        os.umask(0002)
        db = os.path.join(self.config.DATABASE, 'db')

        # lock it
        lockfilenm = db[:-3] + 'lck'
        self.lockfile = locking.acquire_lock(lockfilenm)
        self.lockfile.write(str(os.getpid()))
        self.lockfile.flush()

        self.conn = sqlite.connect(db=db)
        self.cursor = self.conn.cursor()
        try:
            self.database_schema = self.load_dbschema()
        except sqlite.DatabaseError, error:
            if str(error) != 'no such table: schema':
                raise
            self.database_schema = {}
            self.cursor.execute('create table schema (schema varchar)')
            self.cursor.execute('create table ids (name varchar, num integer)')

    def close(self):
        ''' Close off the connection.

            Squash any error caused by us already having closed the
            connection.
        '''
        try:
            self.conn.close()
        except sqlite.ProgrammingError, value:
            if str(value) != 'close failed - Connection is closed.':
                raise

        # release the lock too
        if self.lockfile is not None:
            locking.release_lock(self.lockfile)
        if self.lockfile is not None:
            self.lockfile.close()
            self.lockfile = None

    def rollback(self):
        ''' Reverse all actions from the current transaction.

            Undo all the changes made since the database was opened or the
            last commit() or rollback() was performed.

            Squash any error caused by us having closed the connection (and
            therefore not having anything to roll back)
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'rollback', (self,)

        # roll back
        try:
            self.conn.rollback()
        except sqlite.ProgrammingError, value:
            if str(value) != 'rollback failed - Connection is closed.':
                raise

        # roll back "other" transaction stuff
        for method, args in self.transactions:
            # delete temporary files
            if method == self.doStoreFile:
                self.rollbackStoreFile(*args)
        self.transactions = []

        # clear the cache
        self.clearCache()

    def __repr__(self):
        return '<roundlite 0x%x>'%id(self)

    def sql_fetchone(self):
        ''' Fetch a single row. If there's nothing to fetch, return None.
        '''
        return self.cursor.fetchone()

    def sql_fetchall(self):
        ''' Fetch a single row. If there's nothing to fetch, return [].
        '''
        return self.cursor.fetchall()

    def sql_commit(self):
        ''' Actually commit to the database.

            Ignore errors if there's nothing to commit.
        '''
        try:
            self.conn.commit()
        except sqlite.DatabaseError, error:
            if str(error) != 'cannot commit - no transaction is active':
                raise

    def save_dbschema(self, schema):
        ''' Save the schema definition that the database currently implements
        '''
        s = repr(self.database_schema)
        self.sql('insert into schema values (%s)', (s,))

    def load_dbschema(self):
        ''' Load the schema definition that the database currently implements
        '''
        self.cursor.execute('select schema from schema')
        return eval(self.cursor.fetchone()[0])

    def save_journal(self, classname, cols, nodeid, journaldate,
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
        self.cursor.execute(sql, entry)

    def load_journal(self, classname, cols, nodeid):
        ''' Load the journal from the database
        '''
        # now get the journal entries
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
            elif isinstance(prop, Password) and v is not None:
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

