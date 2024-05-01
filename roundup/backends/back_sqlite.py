"""Implements a backend for SQLite.

See https://pysqlite.sourceforge.net/ for pysqlite info


NOTE: we use the rdbms_common table creation methods which define datatypes
for the columns, but sqlite IGNORES these specifications.
"""
__docformat__ = 'restructuredtext'

import logging
import os
import shutil
import time


from roundup import hyperdb, date, password
from roundup.backends import rdbms_common
from roundup.backends import sessions_sqlite
from roundup.backends import sessions_dbm

try:
    from roundup.backends import sessions_redis
except ImportError:
    sessions_redis = None

from roundup.anypy.strings import uany2s

sqlite_version = None
try:
    import sqlite3 as sqlite
    sqlite_version = 3
except ImportError:
    try:
        from pysqlite2 import dbapi2 as sqlite
        if sqlite.version_info < (2, 1, 0):
            raise ValueError('pysqlite2 minimum version is 2.1.0+ '
                             '- %s found' % sqlite.version)
        sqlite_version = 2
    except ImportError:
        raise ValueError("Unable to import sqlite3 or sqlite 2.")


def db_exists(config):
    return os.path.exists(os.path.join(config.DATABASE, 'db'))


def db_nuke(config):
    shutil.rmtree(config.DATABASE)


class Database(rdbms_common.Database):
    """Sqlite DB backend implementation

    attributes:
      dbtype:
        holds the value for the type of db. It is used by indexer to
        identify the database type so it can import the correct indexer
        module when using native text search mode.
    """

    # char to use for positional arguments
    arg = '?'

    dbtype = "sqlite"

    # used by some code to switch styles of query
    implements_intersect = 1

    # used in generic backend to determine if db supports
    # 'DOUBLE PRECISION' for floating point numbers. Note that sqlite
    # already has double precision as its standard 'REAL' type. So this
    # is set to False here.

    implements_double_precision = False

    hyperdb_to_sql_datatypes = {
        hyperdb.String    : 'VARCHAR(255)',  # noqa: E203
        hyperdb.Date      : 'VARCHAR(30)',   # noqa: E203
        hyperdb.Link      : 'INTEGER',       # noqa: E203
        hyperdb.Interval  : 'VARCHAR(255)',  # noqa: E203
        hyperdb.Password  : 'VARCHAR(255)',  # noqa: E203
        hyperdb.Boolean   : 'BOOLEAN',       # noqa: E203
        hyperdb.Number    : 'REAL',          # noqa: E203
        hyperdb.Integer   : 'INTEGER',       # noqa: E203
    }
    hyperdb_to_sql_value = {
        hyperdb.String    : str,                      # noqa: E203
        hyperdb.Date      : lambda x: x.serialise(),  # noqa: E203
        hyperdb.Link      : int,                      # noqa: E203
        hyperdb.Interval  : str,                      # noqa: E203
        hyperdb.Password  : str,                      # noqa: E203
        hyperdb.Boolean   : int,                      # noqa: E203
        hyperdb.Integer   : int,                      # noqa: E203
        hyperdb.Number    : lambda x: x,              # noqa: E203
        hyperdb.Multilink : lambda x: x,    # used in journal marshalling, # noqa: E203
    }
    sql_to_hyperdb_value = {
        hyperdb.String    : uany2s,                        # noqa: E203
        hyperdb.Date      : lambda x: date.Date(str(x)),   # noqa: E203
        hyperdb.Link      : str,  # XXX numeric ids        # noqa: E203
        hyperdb.Interval  : date.Interval,                 # noqa: E203
        hyperdb.Password  : lambda x: password.Password(encrypted=x),  # noqa: E203
        hyperdb.Boolean   : int,                           # noqa: E203
        hyperdb.Integer   : int,                           # noqa: E203
        hyperdb.Number    : rdbms_common._num_cvt,         # noqa: E203
        hyperdb.Multilink : lambda x: x,    # used in journal marshalling, # noqa: E203
    }

    # We can use DBM, redis or SQLite for managing session info and
    # one-time keys:
    # For SQL database storage of this info we have to create separate
    # databases for Otk and Session because SQLite doesn't support
    # concurrent connections to the same database.
    def getSessionManager(self):
        if not self.Session:
            if self.config.SESSIONDB_BACKEND == "redis":
                if sessions_redis is None:
                    self.Session = sessions_sqlite.Sessions(self)
                    raise ValueError("[redis] session is set, but "
                                     "redis module is not found")
                self.Session = sessions_redis.Sessions(self)
            elif self.config.SESSIONDB_BACKEND == "anydbm":
                self.Session = sessions_dbm.Sessions(self)
            else:
                self.Session = sessions_sqlite.Sessions(self)
        return self.Session

    def getOTKManager(self):
        if not self.Otk:
            if self.config.SESSIONDB_BACKEND == "redis":
                if sessions_redis is None:
                    self.Session = sessions_sqlite.OneTimeKeys(self)
                    raise ValueError("[redis] session is set, but "
                                     "redis is not found")
                self.Otk = sessions_redis.OneTimeKeys(self)
            elif self.config.SESSIONDB_BACKEND == "anydbm":
                self.Otk = sessions_dbm.OneTimeKeys(self)
            else:
                self.Otk = sessions_sqlite.OneTimeKeys(self)
        return self.Otk

    def sql_open_connection(self, dbname=None):
        """Open a standard, non-autocommitting connection.

        pysqlite will automatically BEGIN TRANSACTION for us.
        """
        # make sure the database directory exists
        # database itself will be created by sqlite if needed
        if not os.path.isdir(self.config.DATABASE):
            os.makedirs(self.config.DATABASE)

        if dbname:
            db = os.path.join(self.config.DATABASE, 'db-' + dbname)
        else:
            db = os.path.join(self.config.DATABASE, 'db')
        logging.getLogger('roundup.hyperdb').info('open database %r' % db)
        conn = sqlite.connect(db, timeout=self.config.RDBMS_SQLITE_TIMEOUT)
        conn.row_factory = sqlite.Row

        # pysqlite2 / sqlite3 want us to store Unicode in the db but
        # that's not what's been done historically and it's definitely
        # not what the other backends do, so we'll stick with UTF-8
        if sqlite_version in (2, 3):
            conn.text_factory = str

        cursor = conn.cursor()
        return (conn, cursor)

    def open_connection(self):
        # ensure files are group readable and writable
        os.umask(self.config.UMASK)

        (self.conn, self.cursor) = self.sql_open_connection()

        try:
            self.load_dbschema()
        except sqlite.DatabaseError as error:
            if str(error) != 'no such table: schema':
                raise
            self.init_dbschema()
            self.sql('create table schema (schema varchar)')
            self.sql('create table ids (name varchar, num integer)')
            self.sql('create index ids_name_idx on ids(name)')
            self.create_version_2_tables()
            self._add_fts5_table()
            # Set journal mode to WAL.
            self.sql_commit()  # close out rollback journal/transaction
            self.sql('pragma journal_mode=wal')  # set wal
            self.sql_commit()  # close out rollback and commit wal change

    def create_version_2_tables(self):
        self.sql('create table otks (otk_key varchar, '
                 'otk_value varchar, otk_time integer)')
        self.sql('create index otks_key_idx on otks(otk_key)')
        self.sql('create table sessions (session_key varchar, '
                 'session_time integer, session_value varchar)')
        self.sql('create index sessions_key_idx on '
                 'sessions(session_key)')

        # full-text indexing store
        self.sql('CREATE TABLE __textids (_class varchar, '
                 '_itemid varchar, _prop varchar, _textid'
                 ' integer primary key) ')
        self.sql('CREATE TABLE __words (_word varchar, '
                 '_textid integer)')
        self.sql('CREATE INDEX words_word_ids ON __words(_word)')
        self.sql('CREATE INDEX words_by_id ON __words (_textid)')
        self.sql('CREATE UNIQUE INDEX __textids_by_props ON '
                 '__textids (_class, _itemid, _prop)')
        sql = 'insert into ids (name, num) values (%s,%s)' % (
            self.arg, self.arg)
        self.sql(sql, ('__textids', 1))

    def add_new_columns_v2(self):
        # update existing tables to have the new actor column
        tables = self.database_schema['tables']
        for classname, spec in self.classes.items():
            if classname in tables:
                dbspec = tables[classname]
                self.update_class(spec, dbspec, force=1, adding_v2=1)
                # we've updated - don't try again
                tables[classname] = spec.schema()

    def fix_version_3_tables(self):
        # NOOP - no restriction on column length here
        pass

    def _add_fts5_table(self):
        try:
            self.sql('CREATE virtual TABLE __fts USING fts5(_class, '
                 '_itemid, _prop, _textblob)')
        except sqlite.OperationalError:
            available_options = self.cursor.execute(
                'pragma compile_options;').fetchall()
            if 'ENABLE_FTS5' in [opt['compile_options'] for opt 
                                     in available_options]:
                # sqlite supports FTS5 something else has gone wrong
                raise
            else:
                # report a useful error message
                raise  NotImplementedError(
                    "This version of SQLite was not built with support "
                    "for FTS5. SQLite version: %s" % sqlite.sqlite_version)

    def fix_version_6_tables(self):
        # note sqlite has no limit on column size so v6 fixes
        # to __words._word length are not needed.
        # Add native full-text indexing table
        self._add_fts5_table()

    def update_class(self, spec, old_spec, force=0, adding_v2=0):
        """ Determine the differences between the current spec and the
            database version of the spec, and update where necessary.

            If 'force' is true, update the database anyway.

            SQLite doesn't have ALTER TABLE, so we have to copy and
            regenerate the tables with the new schema.
        """
        new_spec = spec.schema()
        new_spec[1].sort()
        old_spec[1].sort()
        if not force and new_spec == old_spec:
            # no changes
            return 0

        logging.getLogger('roundup.hyperdb').info(
            'update_class %s' % spec.classname)

        # detect multilinks that have been removed, and drop their table
        old_has = {}
        for name, prop in old_spec[1]:
            old_has[name] = 1
            if name in spec.properties or not \
               isinstance(prop, hyperdb.Multilink):
                continue
            # it's a multilink, and it's been removed - drop the old
            # table. First drop indexes.
            self.drop_multilink_table_indexes(spec.classname, name)
            sql = 'drop table %s_%s' % (spec.classname, prop)
            self.sql(sql)

        # now figure how we populate the new table
        if adding_v2:
            fetch = ['_activity', '_creation', '_creator']
        else:
            fetch = ['_actor', '_activity', '_creation', '_creator']
        properties = spec.getprops()
        for propname, _x in new_spec[1]:
            prop = properties[propname]
            if isinstance(prop, hyperdb.Multilink):
                if propname not in old_has:
                    # we need to create the new table
                    self.create_multilink_table(spec, propname)
                elif force:
                    tn = '%s_%s' % (spec.classname, propname)
                    # grabe the current values
                    sql = 'select linkid, nodeid from %s' % tn
                    self.sql(sql)
                    rows = self.cursor.fetchall()

                    # drop the old table
                    self.drop_multilink_table_indexes(spec.classname, propname)
                    sql = 'drop table %s' % tn
                    self.sql(sql)

                    # re-create and populate the new table
                    self.create_multilink_table(spec, propname)
                    sql = """insert into %s (linkid, nodeid) values
                        (%s, %s)""" % (tn, self.arg, self.arg)
                    for linkid, nodeid in rows:
                        self.sql(sql, (int(linkid), int(nodeid)))
            elif propname in old_has:
                # we copy this col over from the old table
                fetch.append('_'+propname)

        # select the data out of the old table
        fetch.append('id')
        fetch.append('__retired__')
        fetchcols = ','.join(fetch)
        cn = spec.classname
        sql = 'select %s from _%s' % (fetchcols, cn)
        self.sql(sql)
        olddata = self.cursor.fetchall()

        # TODO: update all the other index dropping code
        self.drop_class_table_indexes(cn, old_spec[0])

        # drop the old table
        self.sql('drop table _%s' % cn)

        # create the new table
        self.create_class_table(spec)

        if olddata:
            inscols = ['id', '_actor', '_activity', '_creation',
                       '_creator', '__retired__']
            for propname, _x in new_spec[1]:
                prop = properties[propname]
                if isinstance(prop, hyperdb.Multilink):
                    continue
                elif isinstance(prop, hyperdb.Interval):
                    inscols.append('_'+propname)
                    inscols.append('__'+propname+'_int__')
                elif propname in old_has:
                    # we copy this col over from the old table
                    inscols.append('_'+propname)

            # do the insert of the old data - the new columns will have
            # NULL values
            args = ','.join([self.arg for x in inscols])
            cols = ','.join(inscols)
            sql = 'insert into _%s (%s) values (%s)' % (cn, cols, args)
            for entry in olddata:
                d = []
                retired_id = None
                for name in inscols:
                    # generate the new value for the Interval int column
                    if name.endswith('_int__'):
                        name = name[2:-6]
                        if sqlite_version in (2, 3):
                            try:
                                v = hyperdb.Interval(entry[name]).as_seconds()
                            except IndexError:
                                v = None
                        elif name in entry:
                            v = hyperdb.Interval(entry[name]).as_seconds()
                        else:
                            v = None
                    elif sqlite_version in (2, 3):
                        try:
                            v = entry[name]
                        except IndexError:
                            v = None
                    else:
                        v = None
                    if name == 'id':
                        retired_id = v
                    elif (name == '__retired__' and retired_id and
                          v not in ['0', 0]):
                        v = retired_id
                    d.append(v)
                self.sql(sql, tuple(d))

        return 1

    def sql_close(self):
        """ Squash any error caused by us already having closed the
            connection.
        """
        try:
            self.conn.close()
        except sqlite.ProgrammingError as value:
            if str(value) != 'close failed - Connection is closed.':
                raise

    def sql_rollback(self):
        """ Squash any error caused by us having closed the connection (and
            therefore not having anything to roll back)
        """
        try:
            self.conn.rollback()
        except sqlite.ProgrammingError as value:
            if str(value) != 'rollback failed - Connection is closed.':
                raise

    def __repr__(self):
        return '<roundlite 0x%x>' % id(self)

    def sql_commit(self):
        """ Actually commit to the database.

            Ignore errors if there's nothing to commit.
        """
        def list_dir(dir):
            import os
            files = os.listdir(self.dir)
            # ['db-journal', 'files', 'db']
            for entry in [''] + files:
                path = self.dir + '/' + entry
                stat = os.stat(path)
                print("file: %s, uid: %s, gid: %s, mode: %o" % (
                    path, stat.st_uid, stat.st_gid, stat.st_mode))

        # Getting sqlite3.OperationalError: disk I/O error
        # in CI. It happens intermittently. Try to get more
        # info about what is happening and retry the commit.
        # Some possibilities:
        #       -journal file not writable
        #       file has disappeared
        #
        # Note after exception self.conn.in_transaction is False
        # but was True before failed commit(). Retry succeeds,
        # but I am not sure it actually does anything.
        # for retry in range(2):
        try:
            self.conn.commit()
        except sqlite.OperationalError as error:
            if str(error) != 'disk I/O error':
                raise
            list_dir(self.dir)
            raise
        except sqlite.DatabaseError as error:
            if str(error) != 'cannot commit - no transaction is active':
                raise
        #   else:
        #       break # out of loop if no exception
        # open a new cursor for subsequent work
        self.cursor = self.conn.cursor()

    def sql_index_exists(self, table_name, index_name):
        self.sql('pragma index_list(%s)' % table_name)
        for entry in self.cursor.fetchall():
            if entry[1] == index_name:
                return 1
        return 0

    # old-skool id generation
    def newid(self, classname):
        """ Generate a new id for the given class
        """

        # Prevent other processes from reading while we increment.
        # Otherwise multiple processes can end up with the same
        # new id and hilarity results.
        #
        # Defeat pysqlite's attempts to do locking by setting
        # isolation_level to None. Pysqlite can commit
        # on it's own even if we don't want it to end the transaction.
        # If we rewrite to use another sqlite library like apsw we
        # don't have to deal with this autocommit/autotransact foolishness.
        self.conn.isolation_level = None
        # Manage the transaction locks manually.
        self.sql("BEGIN IMMEDIATE")

        # get the next ID
        sql = 'select num from ids where name=%s' % self.arg
        self.sql(sql, (classname, ))
        newid = int(self.cursor.fetchone()[0])

        # leave the next larger number as the next newid
        sql = 'update ids set num=num+1 where name=%s' % self.arg
        vals = (classname,)
        self.sql(sql, vals)

        # reset pysqlite's auto transact stuff to default since the
        # rest of the code expects it.
        self.conn.isolation_level = ''
        # commit writing the data, clearing locks for other processes
        # and create a new cursor to the database.
        self.sql_commit()

        # return as string
        return str(newid)

    def setid(self, classname, setid):
        """ Set the id counter: used during import of database

        We add one to make it behave like the sequences in postgres.
        """
        sql = 'update ids set num=%s where name=%s' % (self.arg, self.arg)
        vals = (int(setid)+1, classname)
        self.sql(sql, vals)

    def clear(self):
        rdbms_common.Database.clear(self)
        # set the id counters to 0 (setid adds one) so we start at 1
        for cn in self.classes.keys():
            self.setid(cn, 0)

    def create_class(self, spec):
        rdbms_common.Database.create_class(self, spec)
        sql = 'insert into ids (name, num) values (%s, %s)' % (
            self.arg, self.arg)
        vals = (spec.classname, 1)
        self.sql(sql, vals)

    def load_journal(self, classname, cols, nodeid):
        """We need to turn the sqlite3.Row into a tuple so it can be
            unpacked"""
        l = rdbms_common.Database.load_journal(self,
                                               classname, cols, nodeid)
        cols = range(5)
        return [[row[col] for col in cols] for row in l]


class sqliteClass:
    def filter(self, *args, **kw):
        """ If there's NO matches to a fetch, sqlite returns NULL
            instead of nothing
        """
        return [f for f in rdbms_common.Class.filter(self, *args, **kw) if f]


class Class(sqliteClass, rdbms_common.Class):
    pass


class IssueClass(sqliteClass, rdbms_common.IssueClass):
    pass


class FileClass(sqliteClass, rdbms_common.FileClass):
    pass

# vim: set et sts=4 sw=4 :
