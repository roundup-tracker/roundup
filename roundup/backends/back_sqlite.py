# $Id: back_sqlite.py,v 1.16 2004-03-15 05:50:20 richard Exp $
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
            self.init_dbschema()
            self.cursor.execute('create table schema (schema varchar)')
            self.cursor.execute('create table ids (name varchar, num integer)')
            self.cursor.execute('create index ids_name_idx on ids(name)')
            self.create_version_2_tables()

    def create_version_2_tables(self):
        self.cursor.execute('create table otks (otk_key varchar, '
            'otk_value varchar, otk_time varchar)')
        self.cursor.execute('create index otks_key_idx on otks(otk_key)')
        self.cursor.execute('create table sessions (s_key varchar, '
            's_last_use varchar, s_user varchar)')
        self.cursor.execute('create index sessions_key_idx on sessions(s_key)')

    def add_actor_column(self):
        # update existing tables to have the new actor column
        tables = self.database_schema['tables']
        for classname, spec in self.classes.items():
            if tables.has_key(classname):
                dbspec = tables[classname]
                self.update_class(spec, dbspec, force=1, adding_actor=1)

    def update_class(self, spec, old_spec, force=0, adding_actor=0):
        ''' Determine the differences between the current spec and the
            database version of the spec, and update where necessary.

            If 'force' is true, update the database anyway.

            SQLite doesn't have ALTER TABLE, so we have to copy and
            regenerate the tables with the new schema.
        '''
        new_has = spec.properties.has_key
        new_spec = spec.schema()
        new_spec[1].sort()
        old_spec[1].sort()
        if not force and new_spec == old_spec:
            # no changes
            return 0

        if __debug__:
            print >>hyperdb.DEBUG, 'update_class FIRING'

        # detect multilinks that have been removed, and drop their table
        old_has = {}
        for name,prop in old_spec[1]:
            old_has[name] = 1
            if new_has(name) or not isinstance(prop, hyperdb.Multilink):
                continue
            # it's a multilink, and it's been removed - drop the old
            # table. First drop indexes.
            self.drop_multilink_table_indexes(spec.classname, ml)
            sql = 'drop table %s_%s'%(spec.classname, prop)
            if __debug__:
                print >>hyperdb.DEBUG, 'update_class', (self, sql)
            self.cursor.execute(sql)
        old_has = old_has.has_key

        # now figure how we populate the new table
        if adding_actor:
            fetch = ['_activity', '_creation', '_creator']
        else:
            fetch = ['_actor', '_activity', '_creation', '_creator']
        properties = spec.getprops()
        for propname,x in new_spec[1]:
            prop = properties[propname]
            if isinstance(prop, hyperdb.Multilink):
                if force or not old_has(propname):
                    # we need to create the new table
                    self.create_multilink_table(spec, propname)
            elif old_has(propname):
                # we copy this col over from the old table
                fetch.append('_'+propname)

        # select the data out of the old table
        fetch.append('id')
        fetch.append('__retired__')
        fetchcols = ','.join(fetch)
        cn = spec.classname
        sql = 'select %s from _%s'%(fetchcols, cn)
        if __debug__:
            print >>hyperdb.DEBUG, 'update_class', (self, sql)
        self.cursor.execute(sql)
        olddata = self.cursor.fetchall()

        # TODO: update all the other index dropping code
        self.drop_class_table_indexes(cn, old_spec[0])

        # drop the old table
        self.cursor.execute('drop table _%s'%cn)

        # create the new table
        self.create_class_table(spec)

        if olddata:
            # do the insert of the old data - the new columns will have
            # NULL values
            args = ','.join([self.arg for x in fetch])
            sql = 'insert into _%s (%s) values (%s)'%(cn, fetchcols, args)
            if __debug__:
                print >>hyperdb.DEBUG, 'update_class', (self, sql, olddata[0])
            for entry in olddata:
                self.cursor.execute(sql, tuple(entry))

        return 1

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


