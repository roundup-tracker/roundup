# Copyright (c) 2003 Martynas Sklyzmantas, Andrey Lebedev <andrey@micro.lt>
#
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
'''Postgresql backend via psycopg2 for Roundup.'''
__docformat__ = 'restructuredtext'

import logging
import os
import re
import shutil
import time

ISOLATION_LEVEL_READ_UNCOMMITTED = None
ISOLATION_LEVEL_READ_COMMITTED = None
ISOLATION_LEVEL_REPEATABLE_READ = None
ISOLATION_LEVEL_SERIALIZABLE = None

import psycopg2                                                   # noqa: E402
from psycopg2 import ProgrammingError                             # noqa: E402
from psycopg2.extensions import QuotedString                      # noqa: E402
from psycopg2.extensions import ISOLATION_LEVEL_READ_UNCOMMITTED  # noqa: F401 E402
from psycopg2.extensions import ISOLATION_LEVEL_READ_COMMITTED    # noqa: E402
from psycopg2.extensions import ISOLATION_LEVEL_REPEATABLE_READ   # noqa: E402
from psycopg2.extensions import ISOLATION_LEVEL_SERIALIZABLE      # noqa: E402
from psycopg2.extensions import TransactionRollbackError          # noqa: F401 E402

from roundup import hyperdb                   # noqa: E402
from roundup.backends import rdbms_common     # noqa: E402
from roundup.backends import sessions_rdbms   # noqa: E402

isolation_levels = {
    'read uncommitted': ISOLATION_LEVEL_READ_COMMITTED,
    'read committed': ISOLATION_LEVEL_READ_COMMITTED,
    'repeatable read': ISOLATION_LEVEL_REPEATABLE_READ,
    'serializable': ISOLATION_LEVEL_SERIALIZABLE
}


def connection_dict(config, dbnamestr=None):
    ''' read_default_group is MySQL-specific, ignore it '''
    d = rdbms_common.connection_dict(config, dbnamestr)
    if 'read_default_group' in d:
        del d['read_default_group']
    if 'read_default_file' in d:
        del d['read_default_file']
    return d

def _db_schema_split(database_name):
    ''' Split database_name into database and schema parts'''
    if '.' in database_name:
        return database_name.split ('.')
    return (database_name, '')

def db_create(config):
    """Clear all database contents and drop database itself"""
    db_name, schema_name = get_database_schema_names(config)
    if not schema_name:
        command = "CREATE DATABASE \"%s\" WITH ENCODING='UNICODE'" % db_name
        if config.RDBMS_TEMPLATE:
            command = command + " TEMPLATE=%s" % config.RDBMS_TEMPLATE
        logging.getLogger('roundup.hyperdb').info(command)
        db_command(config, command)
    else:
        command = "CREATE SCHEMA \"%s\" AUTHORIZATION \"%s\"" % (
            schema_name, get_database_user_name(config))
        logging.getLogger('roundup.hyperdb').info(command)
        db_command(config, command, db_name)

def db_nuke(config):
    """Drop the database (and all its contents) or the schema."""
    db_name, schema_name = get_database_schema_names(config)
    if not schema_name:
        command = 'DROP DATABASE "%s"'% db_name
        logging.getLogger('roundup.hyperdb').info(command)
        db_command(config, command)
    else:
        command = 'DROP SCHEMA "%s" CASCADE' % schema_name
        logging.getLogger('roundup.hyperdb').info(command)
        db_command(config, command, db_name)
    if os.path.exists(config.DATABASE):
        shutil.rmtree(config.DATABASE)

def get_database_schema_names(config):
    '''Get database and schema names using config.RDBMS_NAME or service
       defined by config.RDBMS_SERVICE.

       If database specifed using RDBMS_SERVICE does not exist, the
       error message is parsed for the database name. This database
       can then be created by calling code. Parsing will fail if the
       error message changes. The alternative is to try to find and
       parse the .pg_service .ini style file on unix/windows. This is
       less palatable.

       If the database specified using RDBMS_SERVICE exists, (e.g. we
       are doing a nuke operation), use
       psycopg.extensions.ConnectionInfo to get the dbname. Also parse
       the search_path options setting to get the schema. Only the
       first element of the search_path is returned.  This requires
       psycopg2 > 2.8 from 2018.
    '''

    if config.RDBMS_NAME:
        return _db_schema_split(config.RDBMS_NAME)

    template1 = connection_dict(config)
    try:
        conn = psycopg2.connect(**template1)
    except psycopg2.OperationalError as message:
        # extract db name from error:
        #  'connection to server at "127.0.0.1", port 5432 failed: \
        #   FATAL:  database "rounduptest" does not exist\n'
        # ugh.
        #
        # Database name is any character sequence not including a " or
        # whitespace. Arguably both are allowed by:
        # 
        #  https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS
        #
        # with suitable quoting but ... really.
        search = re.search(
            r'FATAL:\s+database\s+"([^"\s]*)"\s+does\s+not\s+exist',
            message.args[0])
        if search:
            dbname = search.groups()[0]
            # To use a schema, the db has to have been precreated.
            # So return '' for schema if database does not exist.
            return (dbname, '')

        raise hyperdb.DatabaseError(
            "Unable to determine database from service: %s" % message)

    dbname = psycopg2.extensions.ConnectionInfo(conn).dbname
    schema = ''
    options = psycopg2.extensions.ConnectionInfo(conn).options
    conn.close()

    # Assume schema is first word in the search_path spec.
    # , (for multiple items in path) and whitespace (for another option)
    # end the schema name.
    m = re.search(r'search_path=([^,\s]*)', options)
    if m:
        schema = m.group(1)
        if not schema:
            raise ValueError('Unable to get schema for service: "%s" from options: "%s"' % (template1['service'], options))

    return (dbname, schema)

def get_database_user_name(config):
    '''Get database username using config.RDBMS_USER or return
       user from connection created using config.RDBMS_SERVICE.

       If the database specified using RDBMS_SERVICE does exist, (i.e. we
       are doing a nuke operation), use psycopg.extensions.ConnectionInfo
       to get the user. This requires psycopg2 > 2.8 from 2018.
    '''
    if config.RDBMS_USER:
        return config.RDBMS_USER

    template1 = connection_dict(config)
    try:
        conn = psycopg2.connect(**template1)
    except psycopg2.OperationalError as message:
        # extract db name from error:
        #  'connection to server at "127.0.0.1", port 5432 failed: \
        #   FATAL:  database "rounduptest" does not exist\n'
        # ugh.
        #
        # Database name is any character sequence not including a " or
        # whitespace. Arguably both are allowed by:
        # 
        #  https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS
        #
        # with suitable quoting but ... really.
        search = re.search(
            r'FATAL:\s+database\s+"([^"\s]*)"\s+does\s+not\s+exist',
            message.args[0])
        if search:
            dbname = search.groups()[0]
            # To have a user, the db has to exist already.
            # so return '' for user.
            return ''

        raise hyperdb.DatabaseError(
            "Unable to determine database from service: %s" % message)

    user = psycopg2.extensions.ConnectionInfo(conn).user
    conn.close()

    return user

def db_command(config, command, database='postgres'):
    '''Perform some sort of database-level command. Retry 10 times if we
    fail by conflicting with another user.

    Since PostgreSQL version 8.1 there is a database "postgres",
    before "template1" seems to have been used, so we fall back to it.
    Compare to issue2550543.
    '''
    template1 = connection_dict(config, 'database')
    template1['database'] = database

    try:
        conn = psycopg2.connect(**template1)
    except psycopg2.OperationalError as message:
        if re.search(r'database ".+" does not exist', str(message)):
            return db_command(config, command, database='template1')
        raise hyperdb.DatabaseError(message)

    conn.set_isolation_level(0)
    cursor = conn.cursor()
    try:
        for _n in range(10):
            if pg_command(cursor, command):
                return
    finally:
        conn.close()
    raise RuntimeError('10 attempts to create database or schema failed when running: %s' % command)


def pg_command(cursor, command, args=()):
    '''Execute the postgresql command, which may be blocked by some other
    user connecting to the database, and return a true value if it succeeds.

    If there is a concurrent update, retry the command.
    '''
    try:
        cursor.execute(command, args)
    except psycopg2.DatabaseError as err:
        response = str(err).split('\n')[0]
        if "FATAL" not in response:
            msgs = (
                'is being accessed by other users',
                'could not serialize access due to concurrent update',
            )
            for msg in msgs:
                if msg in response:
                    time.sleep(0.1)
                    return 0
        raise RuntimeError(response, command, args)
    return 1


def db_exists(config):
    """Check if database or schema already exists"""
    db = connection_dict(config, 'database')
    db_name, schema_name = get_database_schema_names(config)
    if schema_name:
        db['database'] = db_name
    try:
        conn = psycopg2.connect(**db)
        if not schema_name:
            conn.close()
            return 1
    except Exception:
        return 0
    # <schema_name> will have a non-false value here; otherwise one
    #  of the above returns would have returned.
    # Get a count of the number of schemas named <schema_name> (either 0 or 1).
    command = "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s"
    cursor = conn.cursor()
    pg_command(cursor, command, (schema_name,))
    count = cursor.fetchall()[0][0]
    conn.close()
    return count    # 'count' will be 0 or 1.


class Sessions(sessions_rdbms.Sessions):
    def set(self, *args, **kwargs):
        try:
            sessions_rdbms.Sessions.set(self, *args, **kwargs)
        except ProgrammingError as err:
            response = str(err).split('\n')[0]
            if -1 != response.find('ERROR') and \
               -1 != response.find('could not serialize access due to concurrent update'):
                # another client just updated, and we're running on
                # serializable isolation.
                # see http://www.postgresql.org/docs/7.4/interactive/transaction-iso.html
                self.db.rollback()


class Database(rdbms_common.Database):
    """Postgres DB backend implementation

    attributes:
      dbtype:
        holds the value for the type of db. It is used by indexer to
        identify the database type so it can import the correct indexer
        module when using native text search mode.

      import_savepoint_count:
        count the number of savepoints that have been created during
        import. Once the limit of savepoints is reached, a commit is
        done and this is reset to 0.

    """

    arg = '%s'

    dbtype = "postgres"

    import_savepoint_count = 0

    # Value is set from roundup-admin using db.config["RDBMS_SAVEPOINT_LIMIT"]
    # or to the default of 10_000 at runtime. Use 0 here to trigger
    # initialization.
    savepoint_limit = 0

    # used by some code to switch styles of query
    implements_intersect = 1

    def sql_open_connection(self):
        db = connection_dict(self.config, 'database')
        db_name, schema_name = get_database_schema_names(self.config)
        if schema_name:
            db['database'] = db_name

        # database option always present: log it if not null
        if db['database']:
            logging.getLogger('roundup.hyperdb').info(
                'open database %r' % db['database'])
        if 'service' in db:  # only log if used
            logging.getLogger('roundup.hyperdb').info(
                'open database via service %r' % db['service'])
        try:
            conn = psycopg2.connect(**db)
        except psycopg2.OperationalError as message:
            raise hyperdb.DatabaseError(message)

        cursor = conn.cursor()
        if ISOLATION_LEVEL_REPEATABLE_READ is not None:
            lvl = isolation_levels[self.config.RDBMS_ISOLATION_LEVEL]
            conn.set_isolation_level(lvl)

        if schema_name:
            self.sql ('SET search_path TO %s' % schema_name, cursor=cursor)
            # Commit is required so that a subsequent rollback
            #  will not also rollback the search_path change.
            self.sql ('COMMIT', cursor=cursor)
        return (conn, cursor)

    def sql_new_cursor(self, name='default', conn=None, *args, **kw):
        """ Create new cursor, this may need additional parameters for
            performance optimization for different backends.
        """
        use_name = self.config.RDBMS_SERVERSIDE_CURSOR
        kw = {}
        if use_name:
            kw['name'] = name
        if conn is None:
            conn = self.conn
        return conn.cursor(*args, **kw)

    def open_connection(self):
        if not db_exists(self.config):
            db_create(self.config)

        self.conn, self.cursor = self.sql_open_connection()

        try:
            self.load_dbschema()
        except ProgrammingError as message:
            if str(message).find('schema') == -1:
                raise
            self.rollback()
            self.init_dbschema()
            self.sql("CREATE TABLE schema (schema TEXT)")
            self.sql("CREATE TABLE dual (dummy integer)")
            self.sql("insert into dual values (1)")
            self.create_version_2_tables()
            self.fix_version_3_tables()
            # Need to commit here, otherwise otk/session will not find
            # the necessary tables (in a parallel connection!)
            self.commit()
            self._add_fts_table()
            self.commit()

    def checkpoint_data(self, savepoint="importing"):
        """Create a subtransaction savepoint. Allows recovery/retry
           of operation in exception handler because
           postgres requires a rollback in case of error
           generating exception.  Used with
           restore_connection_on_error to handle uniqueness
           conflict in import_table().

           Savepoints take memory resources. Postgres keeps all
           savepoints (rather than overwriting) until a
           commit(). Commit every ~10,000 savepoints to prevent
           running out of memory on import.

           NOTE: a commit outside of this method will not reset the
           import_savepoint_count. This can result in an unneeded
           commit on a new cursor (that has no savepoints) as there is
           no way to find out if there is a savepoint or how many
           savepoints are opened on a db connection/cursor.

           Because an import is a one shot deal and not part of a long
           running daemon (e.g. the roundup-server), I am not too
           worried about it. It will just slow the import down a tad.
        """

        self.sql('SAVEPOINT %s' % savepoint)

        self.import_savepoint_count += 1

        if not self.savepoint_limit:
            if "RDBMS_SAVEPOINT_LIMIT" in self.config.keys():
                # note this config option is created on the fly
                # by admin.py::do_import. It is never listed in
                # config.ini.
                self.savepoint_limit = self.config["RDBMS_SAVEPOINT_LIMIT"]
            else:
                self.savepoint_limit = 10000

        if self.import_savepoint_count > self.savepoint_limit:
            # track savepoints and commit every 10000 (or user value)
            # so we don't run postgres out of memory.  An import of a
            # customer's tracker ran out of memory after importing
            # ~23000 items with: psycopg2.errors.OutOfMemory: out of
            # shared memory HINT: You might need to increase
            # max_locks_per_transaction.

            self.commit()
            self.import_savepoint_count = 0

    def restore_connection_on_error(self, savepoint="importing"):
        """Postgres leaves a connection/cursor in an unusable state
           after an error. Rollback the transaction to a
           previous savepoint and permit a retry of the
           failed statement. Used with checkpoint_data to
           handle uniqueness conflict in import_table().
        """
        self.sql('ROLLBACK TO %s' % savepoint)

    def create_version_2_tables(self):
        # OTK store
        self.sql('''CREATE TABLE otks (otk_key VARCHAR(255),
            otk_value TEXT, otk_time float)''')
        self.sql('CREATE INDEX otks_key_idx ON otks(otk_key)')

        # Sessions store
        self.sql('''CREATE TABLE sessions (
            session_key VARCHAR(255), session_time float,
            session_value TEXT)''')
        self.sql('''CREATE INDEX sessions_key_idx ON
            sessions(session_key)''')

        # full-text indexing store
        self.sql('CREATE SEQUENCE ___textids_ids')
        self.sql('''CREATE TABLE __textids (
            _textid integer primary key, _class VARCHAR(255),
            _itemid VARCHAR(255), _prop VARCHAR(255))''')
        self.sql('''CREATE TABLE __words (_word VARCHAR(%s),
            _textid integer)''' % (self.indexer.maxlength + 5))
        self.sql('CREATE INDEX words_word_idx ON __words(_word)')
        self.sql('CREATE INDEX words_by_id ON __words (_textid)')
        self.sql('CREATE UNIQUE INDEX __textids_by_props ON '
                 '__textids (_class, _itemid, _prop)')

    def fix_version_2_tables(self):
        # Convert journal date column to TIMESTAMP, params column to TEXT
        self._convert_journal_tables()

        # Convert all String properties to TEXT
        self._convert_string_properties()

        # convert session / OTK *_time columns to REAL
        for name in ('otk', 'session'):
            self.sql('drop index %ss_key_idx' % name)
            self.sql('drop table %ss' % name)
            self.sql('''CREATE TABLE %ss (%s_key VARCHAR(255),
                %s_value VARCHAR(255), %s_time REAL)''' % (name, name,
                                                           name, name))
            self.sql('CREATE INDEX %ss_key_idx ON %ss(%s_key)' % (name, name,
                                                                  name))

    def fix_version_3_tables(self):
        rdbms_common.Database.fix_version_3_tables(self)
        self.sql('''CREATE INDEX words_both_idx ON __words
            USING btree (_word, _textid)''')

    def _add_fts_table(self):
        self.sql(
            'CREATE TABLE __fts (_class VARCHAR(255), '
            '_itemid VARCHAR(255), _prop VARCHAR(255), _tsv tsvector)'
        )

        self.sql('CREATE INDEX __fts_idx ON __fts USING GIN (_tsv)')

    def fix_version_6_tables(self):
        # Modify length for __words._word column.
        c = self.cursor
        sql = 'alter table __words alter column _word type varchar(%s)' % (
                                                                  self.arg)
        # Why magic number 5? It was the original offset between
        #   column length and maxlength.
        c.execute(sql, (self.indexer.maxlength + 5,))

        self._add_fts_table()

    def fix_version_7_tables(self):
        # Modify type for session.session_time/otk.otk_time column.
        # float is double precision 15 signifcant digits
        sql = 'alter table sessions alter column session_time type float'
        self.sql(sql)
        sql = 'alter table otks alter column otk_time type float'
        self.sql(sql)

    def add_new_columns_v2(self):
        # update existing tables to have the new actor column
        tables = self.database_schema['tables']
        for name in tables:
            self.sql('ALTER TABLE _%s add __actor VARCHAR(255)' % name)

    def __repr__(self):
        return '<roundpsycopgsql 0x%x>' % id(self)

    def sql_stringquote(self, value):
        ''' psycopg2.QuotedString returns a "buffer" object with the
            single-quotes around it... '''
        return str(QuotedString(str(value)))[1:-1]

    def sql_index_exists(self, table_name, index_name):
        sql = 'select count(*) from pg_indexes where ' \
            'tablename=%s and indexname=%s' % (self.arg, self.arg)
        self.sql(sql, (table_name, index_name))
        return self.cursor.fetchone()[0]

    def create_class_table(self, spec, create_sequence=1):
        if create_sequence:
            sql = 'CREATE SEQUENCE _%s_ids' % spec.classname
            self.sql(sql)

        return rdbms_common.Database.create_class_table(self, spec)

    def drop_class_table(self, cn):
        sql = 'drop table _%s' % cn
        self.sql(sql)

        sql = 'drop sequence _%s_ids' % cn
        self.sql(sql)

    def newid(self, classname):
        sql = "select nextval('_%s_ids') from dual" % classname
        self.sql(sql)
        return str(self.cursor.fetchone()[0])

    def setid(self, classname, setid):
        sql = "select setval('_%s_ids', %s) from dual" % (classname,
                                                          int(setid))
        self.sql(sql)

    def clear(self):
        rdbms_common.Database.clear(self)

        # reset the sequences
        for cn in self.classes:
            self.cursor.execute('DROP SEQUENCE _%s_ids' % cn)
            self.cursor.execute('CREATE SEQUENCE _%s_ids' % cn)


class PostgresqlClass:
    order_by_null_values = '(%s is not NULL)'
    case_insensitive_like = 'ILIKE'


class Class(PostgresqlClass, rdbms_common.Class):
    pass


class IssueClass(PostgresqlClass, rdbms_common.IssueClass):
    pass


class FileClass(PostgresqlClass, rdbms_common.FileClass):
    pass

# vim: set et sts=4 sw=4 :
