# $Id: back_sqlite.py,v 1.14 2004-03-05 00:08:09 richard Exp $
'''Implements a backend for SQLite.

See https://pysqlite.sourceforge.net/ for pysqlite info
'''
__docformat__ = 'restructuredtext'

import os, base64, marshal

from roundup import hyperdb
from roundup.backends import rdbms_common
from roundup.backends import locking
import sqlite

class Database(rdbms_common.Database):
    # char to use for positional arguments
    arg = '%s'

    def sql_open_connection(self):
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
            self.load_dbschema()
        except sqlite.DatabaseError, error:
            if str(error) != 'no such table: schema':
                raise
            self.database_schema = {}
            self.cursor.execute('create table schema (schema varchar)')
            self.cursor.execute('create table ids (name varchar, num integer)')
            self.cursor.execute('create index ids_name_idx on ids(name)')
            self.create_version_2_tables()

    def create_version_2_tables(self):
        self.cursor.execute('create table otks (key varchar, '
            'value varchar, __time varchar)')
        self.cursor.execute('create index otks_key_idx on otks(key)')
        self.cursor.execute('create table sessions (key varchar, '
            'last_use varchar, user varchar)')
        self.cursor.execute('create index sessions_key_idx on sessions(key)')

    def sql_close(self):
        ''' Squash any error caused by us already having closed the
            connection.
        '''
        try:
            self.conn.close()
        except sqlite.ProgrammingError, value:
            if str(value) != 'close failed - Connection is closed.':
                raise

    def sql_rollback(self):
        ''' Squash any error caused by us having closed the connection (and
            therefore not having anything to roll back)
        '''
        try:
            self.conn.rollback()
        except sqlite.ProgrammingError, value:
            if str(value) != 'rollback failed - Connection is closed.':
                raise

    def __repr__(self):
        return '<roundlite 0x%x>'%id(self)

    def sql_commit(self):
        ''' Actually commit to the database.

            Ignore errors if there's nothing to commit.
        '''
        try:
            self.conn.commit()
        except sqlite.DatabaseError, error:
            if str(error) != 'cannot commit - no transaction is active':
                raise

    def sql_index_exists(self, table_name, index_name):
        self.cursor.execute('pragma index_list(%s)'%table_name)
        for entry in self.cursor.fetchall():
            if entry[1] == index_name:
                return 1
        return 0

class sqliteClass:
    def filter(self, search_matches, filterspec, sort=(None,None),
            group=(None,None)):
        ''' If there's NO matches to a fetch, sqlite returns NULL
            instead of nothing
        '''
        return filter(None, rdbms_common.Class.filter(self, search_matches,
            filterspec, sort=sort, group=group))

class Class(sqliteClass, rdbms_common.Class):
    pass

class IssueClass(sqliteClass, rdbms_common.IssueClass):
    pass

class FileClass(sqliteClass, rdbms_common.FileClass):
    pass


