"""Implements a backend for SQLite.

See https://pysqlite.sourceforge.net/ for pysqlite info


NOTE: we use the rdbms_common table creation methods which define datatypes
for the columns, but sqlite IGNORES these specifications.
"""
__docformat__ = 'restructuredtext'

import os, base64, marshal, shutil, time, logging

from roundup import hyperdb, date, password
from roundup.backends import rdbms_common
sqlite_version = None
try:
    import sqlite3 as sqlite
    sqlite_version = 3
except ImportError:
    try:
        from pysqlite2 import dbapi2 as sqlite
        if sqlite.version_info < (2,1,0):
            raise ValueError('pysqlite2 minimum version is 2.1.0+ '
                '- %s found'%sqlite.version)
        sqlite_version = 2
    except ImportError:
        import sqlite
        sqlite_version = 1

def db_exists(config):
    return os.path.exists(os.path.join(config.DATABASE, 'db'))

def db_nuke(config):
    shutil.rmtree(config.DATABASE)

class Database(rdbms_common.Database):
    # char to use for positional arguments
    if sqlite_version in (2,3):
        arg = '?'
    else:
        arg = '%s'

    # used by some code to switch styles of query
    implements_intersect = 1

    hyperdb_to_sql_datatypes = {
        hyperdb.String : 'VARCHAR(255)',
        hyperdb.Date   : 'VARCHAR(30)',
        hyperdb.Link   : 'INTEGER',
        hyperdb.Interval  : 'VARCHAR(255)',
        hyperdb.Password  : 'VARCHAR(255)',
        hyperdb.Boolean   : 'BOOLEAN',
        hyperdb.Number    : 'REAL',
    }
    hyperdb_to_sql_value = {
        hyperdb.String : str,
        hyperdb.Date   : lambda x: x.serialise(),
        hyperdb.Link   : int,
        hyperdb.Interval  : str,
        hyperdb.Password  : str,
        hyperdb.Boolean   : int,
        hyperdb.Number    : lambda x: x,
        hyperdb.Multilink : lambda x: x,    # used in journal marshalling
    }
    sql_to_hyperdb_value = {
        hyperdb.String : lambda x: isinstance(x, unicode) and x.encode('utf8') or str(x),
        hyperdb.Date   : lambda x: date.Date(str(x)),
        hyperdb.Link   : str, # XXX numeric ids
        hyperdb.Interval  : date.Interval,
        hyperdb.Password  : lambda x: password.Password(encrypted=x),
        hyperdb.Boolean   : int,
        hyperdb.Number    : rdbms_common._num_cvt,
        hyperdb.Multilink : lambda x: x,    # used in journal marshalling
    }

    def sqlite_busy_handler(self, data, table, count):
        """invoked whenever SQLite tries to access a database that is locked"""
        if count == 1:
            # use a 30 second timeout (extraordinarily generous)
            # for handling locked database
            self._busy_handler_endtime = time.time() + 30
        elif time.time() > self._busy_handler_endtime:
            # timeout expired - no more retries
            return 0
        # sleep adaptively as retry count grows,
        # starting from about half a second
        time_to_sleep = 0.01 * (2 << min(5, count))
        time.sleep(time_to_sleep)
        return 1

    def sql_open_connection(self):
        """Open a standard, non-autocommitting connection.

        pysqlite will automatically BEGIN TRANSACTION for us.
        """
        # make sure the database directory exists
        # database itself will be created by sqlite if needed
        if not os.path.isdir(self.config.DATABASE):
            os.makedirs(self.config.DATABASE)

        db = os.path.join(self.config.DATABASE, 'db')
        logging.getLogger('hyperdb').info('open database %r'%db)
        # set a 30 second timeout (extraordinarily generous) for handling
        # locked database
        if sqlite_version == 1:
            conn = sqlite.connect(db=db)
            conn.db.sqlite_busy_handler(self.sqlite_busy_handler)
        else:
            conn = sqlite.connect(db, timeout=30)
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
        except sqlite.DatabaseError, error:
            if str(error) != 'no such table: schema':
                raise
            self.init_dbschema()
            self.sql('create table schema (schema varchar)')
            self.sql('create table ids (name varchar, num integer)')
            self.sql('create index ids_name_idx on ids(name)')
            self.create_version_2_tables()

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
            '_itemid varchar, _prop varchar, _textid integer primary key) ')
        self.sql('CREATE TABLE __words (_word varchar, '
            '_textid integer)')
        self.sql('CREATE INDEX words_word_ids ON __words(_word)')
        self.sql('CREATE INDEX words_by_id ON __words (_textid)')
        self.sql('CREATE UNIQUE INDEX __textids_by_props ON '
                 '__textids (_class, _itemid, _prop)')
        sql = 'insert into ids (name, num) values (%s,%s)'%(self.arg, self.arg)
        self.sql(sql, ('__textids', 1))

    def add_new_columns_v2(self):
        # update existing tables to have the new actor column
        tables = self.database_schema['tables']
        for classname, spec in self.classes.items():
            if tables.has_key(classname):
                dbspec = tables[classname]
                self.update_class(spec, dbspec, force=1, adding_v2=1)
                # we've updated - don't try again
                tables[classname] = spec.schema()

    def fix_version_3_tables(self):
        # NOOP - no restriction on column length here
        pass

    def update_class(self, spec, old_spec, force=0, adding_v2=0):
        """ Determine the differences between the current spec and the
            database version of the spec, and update where necessary.

            If 'force' is true, update the database anyway.

            SQLite doesn't have ALTER TABLE, so we have to copy and
            regenerate the tables with the new schema.
        """
        new_has = spec.properties.has_key
        new_spec = spec.schema()
        new_spec[1].sort()
        old_spec[1].sort()
        if not force and new_spec == old_spec:
            # no changes
            return 0

        logging.getLogger('hyperdb').info('update_class %s'%spec.classname)

        # detect multilinks that have been removed, and drop their table
        old_has = {}
        for name, prop in old_spec[1]:
            old_has[name] = 1
            if new_has(name) or not isinstance(prop, hyperdb.Multilink):
                continue
            # it's a multilink, and it's been removed - drop the old
            # table. First drop indexes.
            self.drop_multilink_table_indexes(spec.classname, name)
            sql = 'drop table %s_%s'%(spec.classname, prop)
            self.sql(sql)
        old_has = old_has.has_key

        # now figure how we populate the new table
        if adding_v2:
            fetch = ['_activity', '_creation', '_creator']
        else:
            fetch = ['_actor', '_activity', '_creation', '_creator']
        properties = spec.getprops()
        for propname,x in new_spec[1]:
            prop = properties[propname]
            if isinstance(prop, hyperdb.Multilink):
                if not old_has(propname):
                    # we need to create the new table
                    self.create_multilink_table(spec, propname)
                elif force:
                    tn = '%s_%s'%(spec.classname, propname)
                    # grabe the current values
                    sql = 'select linkid, nodeid from %s'%tn
                    self.sql(sql)
                    rows = self.cursor.fetchall()

                    # drop the old table
                    self.drop_multilink_table_indexes(spec.classname, propname)
                    sql = 'drop table %s'%tn
                    self.sql(sql)

                    # re-create and populate the new table
                    self.create_multilink_table(spec, propname)
                    sql = """insert into %s (linkid, nodeid) values
                        (%s, %s)"""%(tn, self.arg, self.arg)
                    for linkid, nodeid in rows:
                        self.sql(sql, (int(linkid), int(nodeid)))
            elif old_has(propname):
                # we copy this col over from the old table
                fetch.append('_'+propname)

        # select the data out of the old table
        fetch.append('id')
        fetch.append('__retired__')
        fetchcols = ','.join(fetch)
        cn = spec.classname
        sql = 'select %s from _%s'%(fetchcols, cn)
        self.sql(sql)
        olddata = self.cursor.fetchall()

        # TODO: update all the other index dropping code
        self.drop_class_table_indexes(cn, old_spec[0])

        # drop the old table
        self.sql('drop table _%s'%cn)

        # create the new table
        self.create_class_table(spec)

        if olddata:
            inscols = ['id', '_actor', '_activity', '_creation', '_creator']
            for propname,x in new_spec[1]:
                prop = properties[propname]
                if isinstance(prop, hyperdb.Multilink):
                    continue
                elif isinstance(prop, hyperdb.Interval):
                    inscols.append('_'+propname)
                    inscols.append('__'+propname+'_int__')
                elif old_has(propname):
                    # we copy this col over from the old table
                    inscols.append('_'+propname)

            # do the insert of the old data - the new columns will have
            # NULL values
            args = ','.join([self.arg for x in inscols])
            cols = ','.join(inscols)
            sql = 'insert into _%s (%s) values (%s)'%(cn, cols, args)
            for entry in olddata:
                d = []
                for name in inscols:
                    # generate the new value for the Interval int column
                    if name.endswith('_int__'):
                        name = name[2:-6]
                        if sqlite_version in (2,3):
                            try:
                                v = hyperdb.Interval(entry[name]).as_seconds()
                            except IndexError:
                                v = None
                        elif entry.has_key(name):
                            v = hyperdb.Interval(entry[name]).as_seconds()
                        else:
                            v = None
                    elif sqlite_version in (2,3):
                        try:
                            v = entry[name]
                        except IndexError:
                            v = None
                    elif (sqlite_version == 1 and entry.has_key(name)):
                        v = entry[name]
                    else:
                        v = None
                    d.append(v)
                self.sql(sql, tuple(d))

        return 1

    def sql_close(self):
        """ Squash any error caused by us already having closed the
            connection.
        """
        try:
            self.conn.close()
        except sqlite.ProgrammingError, value:
            if str(value) != 'close failed - Connection is closed.':
                raise

    def sql_rollback(self):
        """ Squash any error caused by us having closed the connection (and
            therefore not having anything to roll back)
        """
        try:
            self.conn.rollback()
        except sqlite.ProgrammingError, value:
            if str(value) != 'rollback failed - Connection is closed.':
                raise

    def __repr__(self):
        return '<roundlite 0x%x>'%id(self)

    def sql_commit(self, fail_ok=False):
        """ Actually commit to the database.

            Ignore errors if there's nothing to commit.
        """
        try:
            self.conn.commit()
        except sqlite.DatabaseError, error:
            if str(error) != 'cannot commit - no transaction is active':
                raise
        # open a new cursor for subsequent work
        self.cursor = self.conn.cursor()

    def sql_index_exists(self, table_name, index_name):
        self.sql('pragma index_list(%s)'%table_name)
        for entry in self.cursor.fetchall():
            if entry[1] == index_name:
                return 1
        return 0

    # old-skool id generation
    def newid(self, classname):
        """ Generate a new id for the given class
        """
        # get the next ID
        sql = 'select num from ids where name=%s'%self.arg
        self.sql(sql, (classname, ))
        newid = int(self.cursor.fetchone()[0])

        # update the counter
        sql = 'update ids set num=%s where name=%s'%(self.arg, self.arg)
        vals = (int(newid)+1, classname)
        self.sql(sql, vals)

        # return as string
        return str(newid)

    def setid(self, classname, setid):
        """ Set the id counter: used during import of database

        We add one to make it behave like the sequences in postgres.
        """
        sql = 'update ids set num=%s where name=%s'%(self.arg, self.arg)
        vals = (int(setid)+1, classname)
        self.sql(sql, vals)

    def clear(self):
        rdbms_common.Database.clear(self)
        # set the id counters to 0 (setid adds one) so we start at 1
        for cn in self.classes.keys():
            self.setid(cn, 0)

    def create_class(self, spec):
        rdbms_common.Database.create_class(self, spec)
        sql = 'insert into ids (name, num) values (%s, %s)'%(self.arg, self.arg)
        vals = (spec.classname, 1)
        self.sql(sql, vals)

    if sqlite_version in (2,3):
        def load_journal(self, classname, cols, nodeid):
            """We need to turn the sqlite3.Row into a tuple so it can be
            unpacked"""
            l = rdbms_common.Database.load_journal(self,
                classname, cols, nodeid)
            cols = range(5)
            return [[row[col] for col in cols] for row in l]

class sqliteClass:
    def filter(self, search_matches, filterspec, sort=(None,None),
            group=(None,None)):
        """ If there's NO matches to a fetch, sqlite returns NULL
            instead of nothing
        """
        return filter(None, rdbms_common.Class.filter(self, search_matches,
            filterspec, sort=sort, group=group))

class Class(sqliteClass, rdbms_common.Class):
    pass

class IssueClass(sqliteClass, rdbms_common.IssueClass):
    pass

class FileClass(sqliteClass, rdbms_common.FileClass):
    pass

# vim: set et sts=4 sw=4 :
