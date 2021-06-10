#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
#
""" Relational database (SQL) backend common code.

Basics:

- map roundup classes to relational tables
- automatically detect schema changes and modify the table schemas
  appropriately (we store the "database version" of the schema in the
  database itself as the only row of the "schema" table)
- multilinks (which represent a many-to-many relationship) are handled through
  intermediate tables
- journals are stored adjunct to the per-class tables
- table names and columns have "_" prepended so the names can't clash with
  restricted names (like "order")
- retirement is determined by the __retired__ column being > 0

Database-specific changes may generally be pushed out to the overridable
sql_* methods, since everything else should be fairly generic. There's
probably a bit of work to be done if a database is used that actually
honors column typing, since the initial databases don't (sqlite stores
everything as a string.)

The schema of the hyperdb being mapped to the database is stored in the
database itself as a repr()'ed dictionary of information about each Class
that maps to a table. If that information differs from the hyperdb schema,
then we update it. We also store in the schema dict a version which
allows us to upgrade the database schema when necessary. See upgrade_db().

To force a unqiueness constraint on the key properties we put the item
id into the __retired__ column duing retirement (so it's 0 for "active"
items) and place a unqiueness constraint on key + __retired__. This is
particularly important for the users class where multiple users may
try to have the same username, with potentially many retired users with
the same name.
"""
__docformat__ = 'restructuredtext'

# standard python modules
import os, time, re, weakref, copy, logging, datetime

# roundup modules
from roundup import hyperdb, date, password, roundupdb, security, support
from roundup.hyperdb import String, Password, Date, Interval, Link, \
    Multilink, DatabaseError, Boolean, Number, Integer
from roundup.i18n import _

# support
from roundup.backends.blobfiles import FileStorage
from roundup.backends.indexer_common import get_indexer
from roundup.backends.sessions_rdbms import Sessions, OneTimeKeys
from roundup.date import Range

from roundup.mlink_expr import compile_expression
from roundup.anypy.strings import b2s, bs2b, us2s, repr_export, eval_import

from hashlib import md5

# dummy value meaning "argument not passed"
_marker = []


def _num_cvt(num):
    num = str(num)
    try:
        return int(num)
    except ValueError:
        return float(num)


def _bool_cvt(value):
    if value in ('TRUE', 'FALSE'):
        return {'TRUE': 1, 'FALSE': 0}[value]
    # assume it's a number returned from the db API
    return int(value)


def date_to_hyperdb_value(d):
    """ convert date d to a roundup date """
    if isinstance(d, datetime.datetime):
        return date.Date(d)
    return date.Date(str(d).replace(' ', '.'))


def connection_dict(config, dbnamestr=None):
    """ Used by Postgresql and MySQL to detemine the keyword args for
    opening the database connection."""
    d = {}
    if dbnamestr:
        d[dbnamestr] = config.RDBMS_NAME
    for name in ('host', 'port', 'password', 'user', 'read_default_group',
                 'read_default_file'):
        cvar = 'RDBMS_'+name.upper()
        if config[cvar] is not None:
            d[name] = config[cvar]
    return d


class IdListOptimizer:
    """ To prevent flooding the SQL parser of the underlaying
        db engine with "x IN (1, 2, 3, ..., <large number>)" collapses
        these cases to "x BETWEEN 1 AND <large number>".
    """

    def __init__(self):
        self.ranges = []
        self.singles = []

    def append(self, nid):
        """ Invariant: nid are ordered ascending """
        if self.ranges:
            last = self.ranges[-1]
            if last[1] == nid-1:
                last[1] = nid
                return
        if self.singles:
            last = self.singles[-1]
            if last == nid-1:
                self.singles.pop()
                self.ranges.append([last, nid])
                return
        self.singles.append(nid)

    def where(self, field, placeholder):
        ranges = self.ranges
        singles = self.singles

        if not singles and not ranges: return "(1=0)", []

        if ranges:
            between = '%s BETWEEN %s AND %s' % (
                field, placeholder, placeholder)
            stmnt = [between] * len(ranges)
        else:
            stmnt = []
        if singles:
            stmnt.append('%s in (%s)' % (
                field, ','.join([placeholder]*len(singles))))

        return '(%s)' % ' OR '.join(stmnt), sum(ranges, []) + singles

    def __str__(self):
        return "ranges: %r / singles: %r" % (self.ranges, self.singles)


class Database(FileStorage, hyperdb.Database, roundupdb.Database):
    """ Wrapper around an SQL database that presents a hyperdb interface.

        - some functionality is specific to the actual SQL database, hence
          the sql_* methods that are NotImplemented
        - we keep a cache of the latest N row fetches (where N is
          configurable).
    """
    def __init__(self, config, journaltag=None):
        """ Open the database and load the schema from it.
        """
        FileStorage.__init__(self, config.UMASK)
        self.config, self.journaltag = config, journaltag
        self.dir = config.DATABASE
        self.classes = {}
        self.indexer = get_indexer(config, self)
        self.security = security.Security(self)

        # additional transaction support for external files and the like
        self.transactions = []

        # keep a cache of the N most recently retrieved rows of any kind
        # (classname, nodeid) = row
        self.cache_size = config.RDBMS_CACHE_SIZE
        self.clearCache()
        self.stats = {'cache_hits': 0, 'cache_misses': 0, 'get_items': 0,
                      'filtering': 0}

        # make sure the database directory exists
        if not os.path.isdir(self.config.DATABASE):
            os.makedirs(self.config.DATABASE)

        # database lock
        self.lockfile = None

        # Uppercase to not collide with Class names
        self.Session = None
        self.Otk = None

        # open a connection to the database, creating the "conn" attribute
        self.open_connection()

    def clearCache(self):
        self.cache = {}
        self.cache_lru = []
        # upcall is necessary!
        roundupdb.Database.clearCache(self)

    def getSessionManager(self):
        if not self.Session:
            self.Session = Sessions(self)
        return self.Session

    def getOTKManager(self):
        if not self.Otk:
            self.Otk = OneTimeKeys(self)
        return self.Otk

    def open_connection(self):
        """ Open a connection to the database, creating it if necessary.

            Must call self.load_dbschema()
        """
        raise NotImplementedError

    def sql(self, sql, args=None, cursor=None):
        """ Execute the sql with the optional args.
        """
        self.log_debug('SQL %r %r' % (sql, args))
        if not cursor:
            cursor = self.cursor
        if args:
            cursor.execute(sql, args)
        else:
            cursor.execute(sql)

    def sql_fetchone(self):
        """ Fetch a single row. If there's nothing to fetch, return None.
        """
        return self.cursor.fetchone()

    def sql_fetchall(self):
        """ Fetch all rows. If there's nothing to fetch, return [].
        """
        return self.cursor.fetchall()

    def sql_fetchiter(self):
        """ Fetch all row as a generator
        """
        while True:
            row = self.cursor.fetchone()
            if not row: break
            yield row

    def search_stringquote(self, value):
        """ Quote a search string to escape magic search characters
            '%' and '_', also need to quote '\' (first)
            Then put '%' around resulting string for LIKE (or ILIKE) operator
        """
        v = value.replace('\\', '\\\\')
        v = v.replace('%', '\\%')
        v = v.replace('_', '\\_')
        return '%' + v + '%'

    def init_dbschema(self):
        self.database_schema = {
            'version': self.current_db_version,
            'tables': {}
        }

    def load_dbschema(self):
        """ Load the schema definition that the database currently implements
        """
        self.cursor.execute('select schema from schema')
        schema = self.cursor.fetchone()
        if schema:
            # bandit - schema is trusted
            self.database_schema = eval(schema[0])  # nosec
        else:
            self.database_schema = {}

    def save_dbschema(self):
        """ Save the schema definition that the database currently implements
        """
        s = repr(self.database_schema)
        self.sql('delete from schema')
        self.sql('insert into schema values (%s)' % self.arg, (s,))

    def post_init(self):
        """ Called once the schema initialisation has finished.

            We should now confirm that the schema defined by our "classes"
            attribute actually matches the schema in the database.
        """
        super(Database, self).post_init()

        # upgrade the database for column type changes, new internal
        # tables, etc.
        save = self.upgrade_db()

        # handle changes in the schema
        tables = self.database_schema['tables']
        for classname, spec in self.classes.items():
            if classname in tables:
                dbspec = tables[classname]
                if self.update_class(spec, dbspec):
                    tables[classname] = spec.schema()
                    save = 1
            else:
                self.create_class(spec)
                tables[classname] = spec.schema()
                save = 1

        for classname, _spec in list(tables.items()):
            if classname not in self.classes:
                self.drop_class(classname, tables[classname])
                del tables[classname]
                save = 1

        # update the database version of the schema
        if save:
            self.save_dbschema()

        # reindex the db if necessary
        if self.indexer.should_reindex():
            self.reindex()

        # commit
        self.sql_commit()

    # update this number when we need to make changes to the SQL structure
    # of the backen database
    current_db_version = 6
    db_version_updated = False

    def upgrade_db(self):
        """ Update the SQL database to reflect changes in the backend code.

            Return boolean whether we need to save the schema.
        """
        version = self.database_schema.get('version', 1)
        if version > self.current_db_version:
            raise DatabaseError('attempting to run rev %d DATABASE with rev '
                                '%d CODE!' % (version,
                                              self.current_db_version))
        if version == self.current_db_version:
            # nothing to do
            return 0

        if version < 2:
            self.log_info('upgrade to version 2')
            # change the schema structure
            self.database_schema = {'tables': self.database_schema}

            # version 1 didn't have the actor column (note that in
            # MySQL this will also transition the tables to typed columns)
            self.add_new_columns_v2()

            # version 1 doesn't have the OTK, session and indexing in the
            # database
            self.create_version_2_tables()

        if version < 3:
            self.log_info('upgrade to version 3')
            self.fix_version_2_tables()

        if version < 4:
            self.log_info('upgrade to version 4')
            self.fix_version_3_tables()

        if version < 5:
            self.log_info('upgrade to version 5')
            self.fix_version_4_tables()

        if version < 6:
            self.log_info('upgrade to version 6')
            self.fix_version_5_tables()

        self.database_schema['version'] = self.current_db_version
        self.db_version_updated = True
        return 1

    def fix_version_3_tables(self):
        # drop the shorter VARCHAR OTK column and add a new TEXT one
        for name in ('otk', 'session'):
            self.sql('DELETE FROM %ss' % name)
            self.sql('ALTER TABLE %ss DROP %s_value' % (name, name))
            self.sql('ALTER TABLE %ss ADD %s_value TEXT' % (name, name))

    def fix_version_2_tables(self):
        # Default (used by sqlite): NOOP
        pass

    def fix_version_4_tables(self):
        # note this is an explicit call now
        c = self.cursor
        for cn, klass in self.classes.items():
            c.execute('select id from _%s where __retired__<>0' % (cn,))
            for (id,) in c.fetchall():
                c.execute('update _%s set __retired__=%s where id=%s' % (cn,
                                               self.arg, self.arg), (id, id))

            if klass.key:
                self.add_class_key_required_unique_constraint(cn, klass.key)

    def fix_version_5_tables(self):
        # Default (used by sqlite, postgres): NOOP
        # mysql overrides this because it is missing
        # _<class>_key_retired_idx index used to make
        # sure that the key is unique if it was created
        # as version 5.
        pass

    def _convert_journal_tables(self):
        """Get current journal table contents, drop the table and re-create"""
        c = self.cursor
        cols = ','.join('nodeid date tag action params'.split())
        for klass in self.classes.values():
            # slurp and drop
            sql = 'select %s from %s__journal order by date' % \
                  (cols, klass.classname)
            c.execute(sql)
            contents = c.fetchall()
            self.drop_journal_table_indexes(klass.classname)
            c.execute('drop table %s__journal' % klass.classname)

            # re-create and re-populate
            self.create_journal_table(klass)
            a = self.arg
            sql = 'insert into %s__journal (%s) values (%s,%s,%s,%s,%s)' % (
                klass.classname, cols, a, a, a, a, a)
            for row in contents:
                # no data conversion needed
                self.cursor.execute(sql, row)

    def _convert_string_properties(self):
        """Get current Class tables that contain String properties, and
        convert the VARCHAR columns to TEXT"""
        c = self.cursor
        for klass in self.classes.values():
            # slurp and drop
            cols, mls = self.determine_columns(list(klass.properties.items()))
            scols = ','.join([i[0] for i in cols])
            sql = 'select id,%s from _%s' % (scols, klass.classname)
            c.execute(sql)
            contents = c.fetchall()
            self.drop_class_table_indexes(klass.classname, klass.getkey())
            c.execute('drop table _%s' % klass.classname)

            # re-create and re-populate
            self.create_class_table(klass, create_sequence=0)
            a = ','.join([self.arg for i in range(len(cols)+1)])
            sql = 'insert into _%s (id,%s) values (%s)' % (klass.classname,
                                                           scols, a)
            for row in contents:
                l = []
                for entry in row:
                    # mysql will already be a string - psql needs "help"
                    if entry is not None and not isinstance(entry, type('')):
                        entry = str(entry)
                    l.append(entry)
                self.cursor.execute(sql, l)

    def refresh_database(self):
        self.post_init()

    def reindex(self, classname=None, show_progress=False):
        if classname:
            classes = [self.getclass(classname)]
        else:
            classes = list(self.classes.values())
        for klass in classes:
            if show_progress:
                for nodeid in support.Progress('Reindex %s' % klass.classname,
                                               klass.list()):
                    klass.index(nodeid)
            else:
                for nodeid in klass.list():
                    klass.index(nodeid)
        self.indexer.save_index()

    def checkpoint_data(self):
        """Call if you need to commit the state of the database
           so you can try to fix the error rather than rolling back

           Needed for postgres when importing data.
        """
        pass

    def restore_connection_on_error(self):
        """on a database error/exception recover the db connection
           if left in an unusable state (e.g. postgres requires
           a rollback).
        """
        pass

    # Used here in the generic backend to determine if the database
    # supports 'DOUBLE PRECISION' for floating point numbers.
    implements_double_precision = True

    hyperdb_to_sql_datatypes = {
        hyperdb.String    : 'TEXT',
        hyperdb.Date      : 'TIMESTAMP',
        hyperdb.Link      : 'INTEGER',
        hyperdb.Interval  : 'VARCHAR(255)',
        hyperdb.Password  : 'VARCHAR(255)',
        hyperdb.Boolean   : 'BOOLEAN',
        hyperdb.Number    : 'REAL',
        hyperdb.Integer   : 'INTEGER',
    }

    def hyperdb_to_sql_datatype(self, propclass, prop=None):

        datatype = self.hyperdb_to_sql_datatypes.get(propclass)
        if self.implements_double_precision and prop and \
           isinstance(prop, Number) and prop.use_double:
            datatype = 'DOUBLE PRECISION'
        if datatype:
            return datatype

        for k, v in self.hyperdb_to_sql_datatypes.items():
            if issubclass(propclass, k):
                return v

        raise ValueError('%r is not a hyperdb property class' % propclass)

    def determine_columns(self, properties):
        """ Figure the column names and multilink properties from the spec

            "properties" is a list of (name, prop) where prop may be an
            instance of a hyperdb "type" _or_ a string repr of that type.
        """
        cols = [
            ('_actor', self.hyperdb_to_sql_datatype(hyperdb.Link)),
            ('_activity', self.hyperdb_to_sql_datatype(hyperdb.Date)),
            ('_creator', self.hyperdb_to_sql_datatype(hyperdb.Link)),
            ('_creation', self.hyperdb_to_sql_datatype(hyperdb.Date)),
        ]
        mls = []
        # add the multilinks separately
        for col, prop in properties:
            # Computed props are not in the db
            if prop.computed:
                continue

            if isinstance(prop, Multilink):
                mls.append(col)
                continue

            if isinstance(prop, type('')):
                raise ValueError("string property spec!")
                # and prop.find('Multilink') != -1:
                # mls.append(col)

            datatype = self.hyperdb_to_sql_datatype(prop.__class__, prop)
            cols.append(('_'+col, datatype))

            # Intervals stored as two columns
            if isinstance(prop, Interval):
                cols.append(('__'+col+'_int__', 'BIGINT'))

        cols.sort()
        return cols, mls

    def update_class(self, spec, old_spec, force=0):
        """ Determine the differences between the current spec and the
            database version of the spec, and update where necessary.

            If 'force' is true, update the database anyway.
        """
        new_spec = spec.schema()
        new_spec[1].sort()
        old_spec[1].sort()
        if not force and new_spec == old_spec:
            # no changes
            return 0

        if not self.config.RDBMS_ALLOW_ALTER:
            raise DatabaseError(_(
                'ALTER operation disallowed: %(old)r -> %(new)r.'% {
                    'old': old_spec, 'new': new_spec}))

        logger = logging.getLogger('roundup.hyperdb.backend')
        logger.info('update_class %s' % spec.classname)

        logger.debug('old_spec %r' % (old_spec,))
        logger.debug('new_spec %r' % (new_spec,))

        # detect key prop change for potential index change
        keyprop_changes = {}
        if new_spec[0] != old_spec[0]:
            if old_spec[0]:
                keyprop_changes['remove'] = old_spec[0]
            if new_spec[0]:
                keyprop_changes['add'] = new_spec[0]

        # detect multilinks that have been removed, and drop their table
        old_has = {}
        for name, prop in old_spec[1]:
            old_has[name] = 1
            if name in spec.properties and not spec.properties[name].computed:
                continue

            if prop.find('Multilink to') != -1:
                # first drop indexes.
                self.drop_multilink_table_indexes(spec.classname, name)

                # now the multilink table itself
                sql = 'drop table %s_%s' % (spec.classname, name)
            else:
                # if this is the key prop, drop the index first
                if old_spec[0] == prop:
                    self.drop_class_table_key_index(spec.classname, name)
                    del keyprop_changes['remove']

                # drop the column
                sql = 'alter table _%s drop column _%s' % (spec.classname,
                                                           name)

            self.sql(sql)

        # if we didn't remove the key prop just then, but the key prop has
        # changed, we still need to remove the old index
        if 'remove' in keyprop_changes:
            self.drop_class_table_key_index(spec.classname,
                                            keyprop_changes['remove'])

        # add new columns
        for propname, prop in new_spec[1]:
            if propname in old_has:
                continue
            prop = spec.properties[propname]
            if isinstance(prop, Multilink):
                self.create_multilink_table(spec, propname)
            else:
                # add the column
                coltype = self.hyperdb_to_sql_datatype(prop.__class__, prop)
                sql = 'alter table _%s add column _%s %s' % (
                    spec.classname, propname, coltype)
                self.sql(sql)

                # extra Interval column
                if isinstance(prop, Interval):
                    sql = 'alter table _%s add column __%s_int__ BIGINT' % (
                        spec.classname, propname)
                    self.sql(sql)

                # if the new column is a key prop, we need an index!
                if new_spec[0] == propname:
                    self.create_class_table_key_index(spec.classname, propname)
                    del keyprop_changes['add']

        # if we didn't add the key prop just then, but the key prop has
        # changed, we still need to add the new index
        if 'add' in keyprop_changes:
            self.create_class_table_key_index(spec.classname,
                                              keyprop_changes['add'])

        return 1

    def determine_all_columns(self, spec):
        """Figure out the columns from the spec and also add internal columns

        """
        cols, mls = self.determine_columns(list(spec.properties.items()))

        # add on our special columns
        cols.append(('id', 'INTEGER PRIMARY KEY'))
        cols.append(('__retired__', 'INTEGER DEFAULT 0'))
        return cols, mls

    def create_class_table(self, spec):
        """Create the class table for the given Class "spec". Creates the
        indexes too."""
        cols, mls = self.determine_all_columns(spec)

        # create the base table
        scols = ','.join(['%s %s' % x for x in cols])
        sql = 'create table _%s (%s)' % (spec.classname, scols)
        self.sql(sql)

        self.create_class_table_indexes(spec)

        return cols, mls

    def create_class_table_indexes(self, spec):
        """ create the class table for the given spec
        """
        # create __retired__ index
        index_sql2 = 'create index _%s_retired_idx on _%s(__retired__)' % (
                        spec.classname, spec.classname)
        self.sql(index_sql2)

        # create index for key property
        if spec.key:
            index_sql3 = 'create index _%s_%s_idx on _%s(_%s)' % (
                        spec.classname, spec.key,
                        spec.classname, spec.key)
            self.sql(index_sql3)

            # and the unique index for key / retired(id)
            self.add_class_key_required_unique_constraint(spec.classname,
                                                          spec.key)

        # TODO: create indexes on (selected?) Link property columns, as
        # they're more likely to be used for lookup

    def add_class_key_required_unique_constraint(self, cn, key):
        sql = '''create unique index _%s_key_retired_idx
            on _%s(__retired__, _%s)''' % (cn, cn, key)
        try:
            self.sql(sql)
        except Exception:  # nosec
            # XXX catch e.g.:
            # _sqlite.DatabaseError: index _status_key_retired_idx
            #  already exists
            pass

    def drop_class_table_indexes(self, cn, key):
        # drop the old table indexes first
        l = ['_%s_id_idx' % cn, '_%s_retired_idx' % cn]
        if key:
            l.append('_%s_%s_idx' % (cn, key))

        table_name = '_%s' % cn
        for index_name in l:
            if not self.sql_index_exists(table_name, index_name):
                continue
            index_sql = 'drop index '+index_name
            self.sql(index_sql)

    def create_class_table_key_index(self, cn, key):
        """ create the class table for the given spec
        """
        sql = 'create index _%s_%s_idx on _%s(_%s)' % (cn, key, cn, key)
        self.sql(sql)

    def drop_class_table_key_index(self, cn, key):
        table_name = '_%s' % cn
        index_name = '_%s_%s_idx' % (cn, key)
        if self.sql_index_exists(table_name, index_name):
            sql = 'drop index '+index_name
            self.sql(sql)

        # and now the retired unique index too
        index_name = '_%s_key_retired_idx' % cn
        if self.sql_index_exists(table_name, index_name):
            sql = 'drop index '+index_name
            self.sql(sql)

    def create_journal_table(self, spec):
        """ create the journal table for a class given the spec and
            already-determined cols
        """
        # journal table
        cols = ','.join(['%s varchar' % x
                         for x in 'nodeid date tag action params'.split()])
        sql = """create table %s__journal (
            nodeid integer, date %s, tag varchar(255),
            action varchar(255), params text)""" % (spec.classname,
                                    self.hyperdb_to_sql_datatype(hyperdb.Date))
        self.sql(sql)
        self.create_journal_table_indexes(spec)

    def create_journal_table_indexes(self, spec):
        # index on nodeid
        sql = 'create index %s_journ_idx on %s__journal(nodeid)' % (
                        spec.classname, spec.classname)
        self.sql(sql)

    def drop_journal_table_indexes(self, classname):
        index_name = '%s_journ_idx' % classname
        if not self.sql_index_exists('%s__journal' % classname, index_name):
            return
        index_sql = 'drop index '+index_name
        self.sql(index_sql)

    def create_multilink_table(self, spec, ml):
        """ Create a multilink table for the "ml" property of the class
            given by the spec
        """
        # create the table
        sql = 'create table %s_%s (linkid INTEGER, nodeid INTEGER)' % (
            spec.classname, ml)
        self.sql(sql)
        self.create_multilink_table_indexes(spec, ml)

    def create_multilink_table_indexes(self, spec, ml):
        # create index on linkid
        index_sql = 'create index %s_%s_l_idx on %s_%s(linkid)' % (
            spec.classname, ml, spec.classname, ml)
        self.sql(index_sql)

        # create index on nodeid
        index_sql = 'create index %s_%s_n_idx on %s_%s(nodeid)' % (
            spec.classname, ml, spec.classname, ml)
        self.sql(index_sql)

    def drop_multilink_table_indexes(self, classname, ml):
        l = [
            '%s_%s_l_idx' % (classname, ml),
            '%s_%s_n_idx' % (classname, ml)
            ]
        table_name = '%s_%s' % (classname, ml)
        for index_name in l:
            if not self.sql_index_exists(table_name, index_name):
                continue
            index_sql = 'drop index %s' % index_name
            self.sql(index_sql)

    def create_class(self, spec):
        """ Create a database table according to the given spec.
        """

        if not self.config.RDBMS_ALLOW_CREATE:
            raise DatabaseError(_('CREATE operation disallowed: "%s".' %
                                  spec.classname))

        cols, mls = self.create_class_table(spec)
        self.create_journal_table(spec)

        # now create the multilink tables
        for ml in mls:
            self.create_multilink_table(spec, ml)

    def drop_class(self, cn, spec):
        """ Drop the given table from the database.

            Drop the journal and multilink tables too.
        """

        if not self.config.RDBMS_ALLOW_DROP:
            raise DatabaseError(_('DROP operation disallowed: "%s".' % cn))

        properties = spec[1]
        # figure the multilinks
        mls = []
        for propname, prop in properties:
            if isinstance(prop, Multilink):
                mls.append(propname)

        # drop class table and indexes
        self.drop_class_table_indexes(cn, spec[0])

        self.drop_class_table(cn)

        # drop journal table and indexes
        self.drop_journal_table_indexes(cn)
        sql = 'drop table %s__journal' % cn
        self.sql(sql)

        for ml in mls:
            # drop multilink table and indexes
            self.drop_multilink_table_indexes(cn, ml)
            sql = 'drop table %s_%s' % (spec.classname, ml)
            self.sql(sql)

    def drop_class_table(self, cn):
        sql = 'drop table _%s' % cn
        self.sql(sql)

    #
    # Classes
    #
    def __getattr__(self, classname):
        """ A convenient way of calling self.getclass(classname).
        """
        if classname in self.classes:
            return self.classes[classname]
        raise AttributeError(classname)

    def addclass(self, cl):
        """ Add a Class to the hyperdatabase.
        """
        cn = cl.classname
        if cn in self.classes:
            raise ValueError(_('Class "%s" already defined.'%cn))
        self.classes[cn] = cl

        # add default Edit and View permissions
        self.security.addPermission(name="Create", klass=cn,
            description="User is allowed to create "+cn)
        self.security.addPermission(name="Edit", klass=cn,
            description="User is allowed to edit "+cn)
        self.security.addPermission(name="View", klass=cn,
            description="User is allowed to access "+cn)
        self.security.addPermission(name="Retire", klass=cn,
            description="User is allowed to retire "+cn)

    def getclasses(self):
        """ Return a list of the names of all existing classes.
        """
        return sorted(self.classes)

    def getclass(self, classname):
        """Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        """
        try:
            return self.classes[classname]
        except KeyError:
            raise KeyError('There is no class called "%s"' % classname)

    def clear(self):
        """Delete all database contents.

        Note: I don't commit here, which is different behaviour to the
              "nuke from orbit" behaviour in the dbs.
        """
        logging.getLogger('roundup.hyperdb.backend').info('clear')
        for cn in self.classes:
            sql = 'delete from _%s' % cn
            self.sql(sql)

    #
    # Nodes
    #

    hyperdb_to_sql_value = {
        hyperdb.String    : str,
        # fractional seconds by default
        hyperdb.Date      : lambda x: x.formal(sep=' ', sec='%06.3f'),
        hyperdb.Link      : int,
        hyperdb.Interval  : str,
        hyperdb.Password  : str,
        hyperdb.Boolean   : lambda x: x and 'TRUE' or 'FALSE',
        hyperdb.Number    : lambda x: x,
        hyperdb.Integer   : lambda x: x,
        hyperdb.Multilink : lambda x: x,    # used in journal marshalling
    }

    def to_sql_value(self, propklass):

        fn = self.hyperdb_to_sql_value.get(propklass)
        if fn:
            return fn

        for k, v in self.hyperdb_to_sql_value.items():
            if issubclass(propklass, k):
                return v

        raise ValueError('%r is not a hyperdb property class' % propklass)

    def _cache_del(self, key):
        del self.cache[key]
        self.cache_lru.remove(key)

    def _cache_refresh(self, key):
        self.cache_lru.remove(key)
        self.cache_lru.insert(0, key)

    def _cache_save(self, key, node):
        self.cache[key] = node
        # update the LRU
        self.cache_lru.insert(0, key)
        if len(self.cache_lru) > self.cache_size:
            del self.cache[self.cache_lru.pop()]

    def addnode(self, classname, nodeid, node):
        """ Add the specified node to its class's db.
        """
        self.log_debug('addnode %s%s %r' % (classname,
                                            nodeid, node))

        # determine the column definitions and multilink tables
        cl = self.classes[classname]
        cols, mls = self.determine_columns(list(cl.properties.items()))

        # we'll be supplied these props if we're doing an import
        values = node.copy()
        if 'creator' not in values:
            # add in the "calculated" properties (dupe so we don't affect
            # calling code's node assumptions)
            values['creation'] = values['activity'] = date.Date()
            values['actor'] = values['creator'] = self.getuid()

        cl = self.classes[classname]
        props = cl.getprops(protected=1)
        del props['id']

        # default the non-multilink columns
        for col, prop in props.items():
            if col not in values:
                if isinstance(prop, Multilink):
                    values[col] = []
                else:
                    values[col] = None

        # clear this node out of the cache if it's in there
        key = (classname, nodeid)
        if key in self.cache:
            self._cache_del(key)

        # figure the values to insert
        vals = []
        for col, _dt in cols:
            # this is somewhat dodgy....
            if col.endswith('_int__'):
                # XXX eugh, this test suxxors
                value = values[col[2:-6]]
                # this is an Interval special "int" column
                if value is not None:
                    vals.append(value.as_seconds())
                else:
                    vals.append(value)
                continue

            prop = props[col[1:]]
            value = values[col[1:]]
            if value is not None:
                value = self.to_sql_value(prop.__class__)(value)
            vals.append(value)
        vals.append(nodeid)
        vals = tuple(vals)

        # make sure the ordering is correct for column name -> column value
        s = ','.join([self.arg for x in cols]) + ',%s' % self.arg
        cols = ','.join([col for col, dt in cols]) + ',id'

        # perform the inserts
        sql = 'insert into _%s (%s) values (%s)' % (classname, cols, s)
        self.sql(sql, vals)

        # insert the multilink rows
        for col in mls:
            t = '%s_%s' % (classname, col)
            for entry in node[col]:
                sql = 'insert into %s (linkid, nodeid) values (%s,%s)' % (
                    t, self.arg, self.arg)
                self.sql(sql, (entry, nodeid))

    def setnode(self, classname, nodeid, values, multilink_changes={}):
        """ Change the specified node.
        """
        self.log_debug('setnode %s%s %r' % (classname, nodeid, values))

        # clear this node out of the cache if it's in there
        key = (classname, nodeid)
        if key in self.cache:
            self._cache_del(key)

        cl = self.classes[classname]
        props = cl.getprops()

        cols = []
        mls = []
        # add the multilinks separately
        for col in values:
            prop = props[col]
            if isinstance(prop, Multilink):
                mls.append(col)
            elif isinstance(prop, Interval):
                # Intervals store the seconds value too
                cols.append(col)
                # extra leading '_' added by code below
                cols.append('_' + col + '_int__')
            else:
                cols.append(col)
        cols.sort()

        # figure the values to insert
        vals = []
        for col in cols:
            if col.endswith('_int__'):
                # XXX eugh, this test suxxors
                # Intervals store the seconds value too
                col = col[1:-6]
                prop = props[col]
                value = values[col]
                if value is None:
                    vals.append(None)
                else:
                    vals.append(value.as_seconds())
            else:
                prop = props[col]
                value = values[col]
                if value is None:
                    e = None
                else:
                    e = self.to_sql_value(prop.__class__)(value)
                vals.append(e)

        vals.append(int(nodeid))
        vals = tuple(vals)

        # if there's any updates to regular columns, do them
        if cols:
            # make sure the ordering is correct for column name -> column value
            s = ','.join(['_%s=%s' % (x, self.arg) for x in cols])
            cols = ','.join(cols)

            # perform the update
            sql = 'update _%s set %s where id=%s' % (classname, s, self.arg)
            self.sql(sql, vals)

        # we're probably coming from an import, not a change
        if not multilink_changes:
            for name in mls:
                prop = props[name]
                value = values[name]

                t = '%s_%s' % (classname, name)

                # clear out previous values for this node
                # XXX numeric ids
                self.sql('delete from %s where nodeid=%s' % (t, self.arg),
                         (nodeid,))

                # insert the values for this node
                for entry in values[name]:
                    sql = 'insert into %s (linkid, nodeid) values (%s,%s)' % (
                        t, self.arg, self.arg)
                    # XXX numeric ids
                    self.sql(sql, (entry, nodeid))

        # we have multilink changes to apply
        for col, (add, remove) in multilink_changes.items():
            tn = '%s_%s' % (classname, col)
            if add:
                sql = 'insert into %s (nodeid, linkid) values (%s,%s)' % (tn,
                    self.arg, self.arg)
                for addid in add:
                    # XXX numeric ids
                    self.sql(sql, (int(nodeid), int(addid)))
            if remove:
                s = ','.join([self.arg]*len(remove))
                sql = 'delete from %s where nodeid=%s and linkid in (%s)' % (
                    tn, self.arg, s)
                # XXX numeric ids
                self.sql(sql, [int(nodeid)] + remove)

    sql_to_hyperdb_value = {
        hyperdb.String    : us2s,
        hyperdb.Date      : date_to_hyperdb_value,
#        hyperdb.Link   : int,      # XXX numeric ids
        hyperdb.Link      : str,
        hyperdb.Interval  : date.Interval,
        hyperdb.Password  : lambda x: password.Password(encrypted=x),
        hyperdb.Boolean   : _bool_cvt,
        hyperdb.Number    : _num_cvt,
        hyperdb.Integer   : int,
        hyperdb.Multilink : lambda x: x,    # used in journal marshalling
    }

    def to_hyperdb_value(self, propklass):

        fn = self.sql_to_hyperdb_value.get(propklass)
        if fn:
            return fn

        for k, v in self.sql_to_hyperdb_value.items():
            if issubclass(propklass, k):
                return v

        raise ValueError('%r is not a hyperdb property class' % propklass)

    def _materialize_multilink(self, classname, nodeid, node, propname):
        """ evaluation of single Multilink (lazy eval may have skipped this)
        """
        if propname not in node:
            prop = self.getclass(classname).properties[propname]
            tn  = prop.table_name
            lid = prop.linkid_name
            nid = prop.nodeid_name
            w   = ''
            joi = ''
            if prop.computed:
                if isinstance(prop.rev_property, Link):
                    w = ' and %s.__retired__=0'%tn
                else:
                    tn2 = '_' + prop.classname
                    joi = ', %s' % tn2
                    w = ' and %s.%s=%s.id and %s.__retired__=0'%(tn, lid,
                        tn2, tn2)
            cursor = self.sql_new_cursor(name='_materialize_multilink')
            sql = 'select %s from %s%s where %s=%s%s' %(lid, tn, joi, nid,
                self.arg, w)
            self.sql(sql, (nodeid,), cursor)
            # Reduce this to only the first row (the ID), this can save a
            # lot of space for large query results (not using fetchall)
            node[propname] = [str(x) for x in sorted(int(r[0]) for r in cursor)]
            cursor.close()

    def _materialize_multilinks(self, classname, nodeid, node, props=None):
        """ get all Multilinks of a node (lazy eval may have skipped this)
        """
        cl = self.classes[classname]
        props = props or [pn for (pn, p) in cl.properties.items()
                          if isinstance(p, Multilink)]
        for propname in props:
            if propname not in node:
                self._materialize_multilink(classname, nodeid, node, propname)

    def getnode(self, classname, nodeid, fetch_multilinks=True):
        """ Get a node from the database.
            For optimisation optionally we don't fetch multilinks
            (lazy Multilinks).
            But for internal database operations we need them.
        """
        # see if we have this node cached
        key = (classname, nodeid)
        if key in self.cache:
            # push us back to the top of the LRU
            self._cache_refresh(key)
            if __debug__:
                self.stats['cache_hits'] += 1
            # return the cached information
            if fetch_multilinks:
                self._materialize_multilinks(classname, nodeid,
                                             self.cache[key])
            return self.cache[key]

        if __debug__:
            self.stats['cache_misses'] += 1
            start_t = time.time()

        # figure the columns we're fetching
        cl = self.classes[classname]
        cols, mls = self.determine_columns(list(cl.properties.items()))
        scols = ','.join([col for col, dt in cols])

        # perform the basic property fetch
        sql = 'select %s from _%s where id=%s' % (scols, classname, self.arg)
        self.sql(sql, (nodeid,))

        values = self.sql_fetchone()
        if values is None:
            raise IndexError('no such %s %s' % (classname, nodeid))

        # make up the node
        node = {}
        props = cl.getprops(protected=1)
        for col in range(len(cols)):
            name = cols[col][0][1:]
            if name.endswith('_int__'):
                # XXX eugh, this test suxxors
                # ignore the special Interval-as-seconds column
                continue
            value = values[col]
            if value is not None:
                value = self.to_hyperdb_value(props[name].__class__)(value)
            node[name] = value

        if fetch_multilinks and mls:
            self._materialize_multilinks(classname, nodeid, node, mls)

        # save off in the cache
        key = (classname, nodeid)
        self._cache_save(key, node)

        if __debug__:
            self.stats['get_items'] += (time.time() - start_t)

        return node

    def destroynode(self, classname, nodeid):
        """Remove a node from the database. Called exclusively by the
           destroy() method on Class.
        """
        message = 'destroynode %s%s' % (classname, nodeid)
        logging.getLogger('roundup.hyperdb.backend').info(message)

        # make sure the node exists
        if not self.hasnode(classname, nodeid):
            raise IndexError('%s has no node %s' % (classname, nodeid))

        # see if we have this node cached
        if (classname, nodeid) in self.cache:
            del self.cache[(classname, nodeid)]

        # see if there's any obvious commit actions that we should get rid of
        for entry in self.transactions[:]:
            if entry[1][:2] == (classname, nodeid):
                self.transactions.remove(entry)

        # now do the SQL
        sql = 'delete from _%s where id=%s' % (classname, self.arg)
        self.sql(sql, (nodeid,))

        # remove from multilnks
        cl = self.getclass(classname)
        x, mls = self.determine_columns(list(cl.properties.items()))
        for col in mls:
            # get the link ids
            sql = 'delete from %s_%s where nodeid=%s' % (classname, col,
                                                         self.arg)
            self.sql(sql, (nodeid,))

        # remove journal entries
        sql = 'delete from %s__journal where nodeid=%s' % (
            classname, self.arg)
        self.sql(sql, (nodeid,))

        # cleanup any blob filestorage when we commit
        self.transactions.append((FileStorage.destroy, (self,
                                                        classname, nodeid)))

    def hasnode(self, classname, nodeid):
        """ Determine if the database has a given node.
        """
        # nodeid (aka link) is sql type INTEGER.  max positive value
        # for INTEGER is 2^31-1 for Postgres and MySQL. The max
        # positive value for SqLite is 2^63 -1, so arguably this check
        # needs to adapt for the type of the RDBMS. For right now,
        # choose lowest common denominator.
        if int(nodeid) >= 2**31:
            # value out of range return false
            return 0

        # If this node is in the cache, then we do not need to go to
        # the database.  (We don't consider this an LRU hit, though.)
        if (classname, nodeid) in self.cache:
            # Return 1, not True, to match the type of the result of
            # the SQL operation below.
            return 1
        sql = 'select count(*) from _%s where id=%s' % (classname, self.arg)
        self.sql(sql, (nodeid,))
        return int(self.cursor.fetchone()[0])

    def countnodes(self, classname):
        """ Count the number of nodes that exist for a particular Class.
        """
        sql = 'select count(*) from _%s' % classname
        self.sql(sql)
        return self.cursor.fetchone()[0]

    def addjournal(self, classname, nodeid, action, params, creator=None,
                   creation=None):
        """ Journal the Action
        'action' may be:

            'set' -- 'params' is a dictionary of property values
            'create' -- 'params' is an empty dictionary as of
                      Wed Nov 06 11:38:43 2002 +0000
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retired' or 'restored' -- 'params' is None

            'creator' -- the user performing the action, which defaults to
            the current user.
        """
        # handle supply of the special journalling parameters (usually
        # supplied on importing an existing database)
        if creator:
            journaltag = creator
        else:
            journaltag = self.getuid()
        if creation:
            journaldate = creation
        else:
            journaldate = date.Date()

        # create the journal entry
        cols = 'nodeid,date,tag,action,params'

        self.log_debug('addjournal %s%s %r %s %s %r' % (
            classname, nodeid, journaldate, journaltag, action, params))

        # make the journalled data marshallable
        if isinstance(params, type({})):
            self._journal_marshal(params, classname)

        params = repr_export(params)

        dc = self.to_sql_value(hyperdb.Date)
        journaldate = dc(journaldate)

        self.save_journal(classname, cols, nodeid, journaldate,
                          journaltag, action, params)

    def setjournal(self, classname, nodeid, journal):
        """Set the journal to the "journal" list."""
        # clear out any existing entries
        self.sql('delete from %s__journal where nodeid=%s' % (
            classname, self.arg), (nodeid,))

        # create the journal entry
        cols = 'nodeid,date,tag,action,params'

        dc = self.to_sql_value(hyperdb.Date)
        for nodeid, journaldate, journaltag, action, params in journal:
            self.log_debug('addjournal %s%s %r %s %s %r' % (
                classname, nodeid, journaldate, journaltag, action,
                params))

            # make the journalled data marshallable
            if isinstance(params, type({})):
                self._journal_marshal(params, classname)
            params = repr_export(params)

            self.save_journal(classname, cols, nodeid, dc(journaldate),
                              journaltag, action, params)

    def _journal_marshal(self, params, classname):
        """Convert the journal params values into safely repr'able and
        eval'able values."""
        properties = self.getclass(classname).getprops()
        for param, value in params.items():
            if not value:
                continue
            property = properties[param]
            cvt = self.to_sql_value(property.__class__)
            if isinstance(property, Password):
                params[param] = cvt(value)
            elif isinstance(property, Date):
                params[param] = cvt(value)
            elif isinstance(property, Interval):
                params[param] = cvt(value)
            elif isinstance(property, Boolean):
                params[param] = cvt(value)

    def getjournal(self, classname, nodeid):
        """ get the journal for id
        """
        # make sure the node exists
        if not self.hasnode(classname, nodeid):
            raise IndexError('%s has no node %s' % (classname, nodeid))

        cols = ','.join('nodeid date tag action params'.split())
        journal = self.load_journal(classname, cols, nodeid)

        # now unmarshal the data
        dc = self.to_hyperdb_value(hyperdb.Date)
        res = []
        properties = self.getclass(classname).getprops()
        for nodeid, date_stamp, user, action, params in journal:
            params = eval_import(params)
            if isinstance(params, type({})):
                for param, value in params.items():
                    if not value:
                        continue
                    property = properties.get(param, None)
                    if property is None:
                        # deleted property
                        continue
                    cvt = self.to_hyperdb_value(property.__class__)
                    if isinstance(property, Password):
                        params[param] = password.JournalPassword(value)
                    elif isinstance(property, Date):
                        params[param] = cvt(value)
                    elif isinstance(property, Interval):
                        params[param] = cvt(value)
                    elif isinstance(property, Boolean):
                        params[param] = cvt(value)
            # XXX numeric ids
            res.append((str(nodeid), dc(date_stamp), user, action, params))
        return res

    def save_journal(self, classname, cols, nodeid, journaldate,
                     journaltag, action, params):
        """ Save the journal entry to the database
        """
        entry = (nodeid, journaldate, journaltag, action, params)

        # do the insert
        a = self.arg
        sql = 'insert into %s__journal (%s) values (%s,%s,%s,%s,%s)' % (
            classname, cols, a, a, a, a, a)
        self.sql(sql, entry)

    def load_journal(self, classname, cols, nodeid):
        """ Load the journal from the database
        """
        # now get the journal entries
        sql = 'select %s from %s__journal where nodeid=%s order by date' % (
            cols, classname, self.arg)
        self.sql(sql, (nodeid,))
        return self.cursor.fetchall()

    def pack(self, pack_before):
        """ Delete all journal entries except "create" before 'pack_before'.
        """
        date_stamp = self.to_sql_value(Date)(pack_before)

        # do the delete
        for classname in self.classes:
            sql = "delete from %s__journal where date<%s and "\
                "action<>'create'" % (classname, self.arg)
            self.sql(sql, (date_stamp,))

    def sql_commit(self):
        """ Actually commit to the database.
        """
        logging.getLogger('roundup.hyperdb.backend').info('commit')

        self.conn.commit()

        # open a new cursor for subsequent work
        self.cursor = self.conn.cursor()

    def sql_new_cursor(self, conn=None, *args, **kw):
        """ Create new cursor, this may need additional parameters for
            performance optimization for different backends.
        """
        if conn is None:
            conn = self.conn
        return conn.cursor()

    def commit(self):
        """ Commit the current transactions.

        Save all data changed since the database was opened or since the
        last commit() or rollback().
        """
        # commit the database
        self.sql_commit()

        # session and otk are committed with the db but not the other
        # way round
        if self.Session:
            self.Session.commit()
        if self.Otk:
            self.Otk.commit()

        # now, do all the other transaction stuff
        for method, args in self.transactions:
            method(*args)

        # save the indexer
        self.indexer.save_index()

        # clear out the transactions
        self.transactions = []

        # clear the cache: Don't carry over cached values from one
        # transaction to the next (there may be other changes from other
        # transactions)
        self.clearCache()

    def sql_rollback(self):
        self.conn.rollback()

    def rollback(self):
        """ Reverse all actions from the current transaction.

        Undo all the changes made since the database was opened or the last
        commit() or rollback() was performed.
        """
        logging.getLogger('roundup.hyperdb.backend').info('rollback')

        self.sql_rollback()

        # roll back "other" transaction stuff
        for method, args in self.transactions:
            # delete temporary files
            if method == self.doStoreFile:
                self.rollbackStoreFile(*args)
        self.transactions = []

        # clear the cache
        self.clearCache()

    def sql_close(self):
        logging.getLogger('roundup.hyperdb.backend').info('close')
        self.conn.close()

    def close(self):
        """ Close off the connection.
        """
        self.indexer.close()
        self.sql_close()
        if self.Session:
            self.Session.close()
            self.Session = None
        if self.Otk:
            self.Otk.close()
            self.Otk = None


#
# The base Class class
#
class Class(hyperdb.Class):
    """ The handle to a particular class of nodes in a hyperdatabase.

        All methods except __repr__ and getnode must be implemented by a
        concrete backend Class.
    """
    # For many databases the LIKE operator ignores case.
    # Postgres and Oracle have an ILIKE operator to support this.
    # We define the default here, can be changed in derivative class
    case_insensitive_like = 'LIKE'

    # For some databases (mysql) the = operator for strings ignores case.
    # We define the default here, can be changed in derivative class
    case_sensitive_equal = '='

    # Some DBs order NULL values last. Set this variable in the backend
    # for prepending an order by clause for each attribute that causes
    # correct sort order for NULLs. Examples:
    # order_by_null_values = '(%s is not NULL)'
    # order_by_null_values = 'notnull(%s)'
    # The format parameter is replaced with the attribute.
    order_by_null_values = None

    # Assuming DBs can do subselects, overwrite if they cannot.
    supports_subselects = True

    def schema(self):
        """ A dumpable version of the schema that we can store in the
            database
        """
        return (self.key,
          [(x, repr(y)) for x, y in self.properties.items() if not y.computed])

    def enableJournalling(self):
        """Turn journalling on for this class
        """
        self.do_journal = 1

    def disableJournalling(self):
        """Turn journalling off for this class
        """
        self.do_journal = 0

    # Editing nodes:
    def create(self, **propvalues):
        """ Create a new node of this class and return its id.

        The keyword arguments in 'propvalues' map property names to values.

        The values of arguments must be acceptable for the types of their
        corresponding properties or a TypeError is raised.

        If this class has a key property, it must be present and its value
        must not collide with other key strings or a ValueError is raised.

        Any other properties on this class that are missing from the
        'propvalues' dictionary are set to None.

        If an id in a link or multilink property does not refer to a valid
        node, an IndexError is raised.
        """
        self.fireAuditors('create', None, propvalues)
        newid = self.create_inner(**propvalues)
        self.fireReactors('create', newid, None)
        return newid

    def create_inner(self, **propvalues):
        """ Called by create, in-between the audit and react calls.
        """
        if 'id' in propvalues:
            raise KeyError('"id" is reserved')

        if self.db.journaltag is None:
            raise DatabaseError(_('Database open read-only'))

        if ('creator' in propvalues or 'actor' in propvalues or
            'creation' in propvalues or 'activity' in propvalues):
            raise KeyError('"creator", "actor", "creation" and '
                           '"activity" are reserved')

        for p in propvalues:
            prop = self.properties[p]
            if prop.computed:
                raise KeyError('"%s" is a computed property'%p)

        # new node's id
        newid = self.db.newid(self.classname)

        # validate propvalues
        num_re = re.compile(r'^\d+$')
        for key, value in propvalues.items():
            if key == self.key:
                try:
                    self.lookup(value)
                except KeyError:
                    pass
                else:
                    raise ValueError('node with key "%s" exists' % value)

            # try to handle this property
            try:
                prop = self.properties[key]
            except KeyError:
                raise KeyError('"%s" has no property "%s"' % (self.classname,
                                                              key))

            if value is not None and isinstance(prop, Link):
                if not isinstance(value, type('')):
                    raise ValueError('link value must be String')
                link_class = self.properties[key].classname
                # if it isn't a number, it's a key
                if not num_re.match(value):
                    try:
                        value = self.db.classes[link_class].lookup(value)
                    except (TypeError, KeyError):
                        raise IndexError('new property "%s": %s not a %s' % (
                            key, value, link_class))
                elif not self.db.getclass(link_class).hasnode(value):
                    raise IndexError('%s has no node %s' % (link_class,
                                                            value))

                # save off the value
                propvalues[key] = value

                # register the link with the newly linked node
                if self.do_journal and self.properties[key].do_journal:
                    self.db.addjournal(link_class, value, 'link',
                                       (self.classname, newid, key))

            elif isinstance(prop, Multilink):
                if value is None:
                    value = []
                if not hasattr(value, '__iter__') or \
                   isinstance(value, type('')):
                    raise TypeError('new property "%s" not an iterable of ids'
                                    % key)
                # clean up and validate the list of links
                link_class = self.properties[key].classname
                l = []
                for entry in value:
                    if not isinstance(entry, type('')):
                        raise ValueError('"%s" multilink value (%r) '
                                         'must contain Strings' % (
                                             key, value))
                    # if it isn't a number, it's a key
                    if not num_re.match(entry):
                        try:
                            entry = self.db.classes[link_class].lookup(entry)
                        except (TypeError, KeyError):
                            raise IndexError('new property "%s": %s not a %s' % (
                                key, entry, self.properties[key].classname))
                    l.append(entry)
                value = l
                propvalues[key] = value

                # handle additions
                for nodeid in value:
                    if not self.db.getclass(link_class).hasnode(nodeid):
                        raise IndexError('%s has no node %s' % (link_class,
                                                                nodeid))
                    # register the link with the newly linked node
                    if self.do_journal and self.properties[key].do_journal:
                        self.db.addjournal(link_class, nodeid, 'link',
                                           (self.classname, newid, key))

            elif isinstance(prop, String):
                if type(value) != type('') and type(value) != type(u''):
                    raise TypeError('new property "%s" not a string'%key)
                if prop.indexme:
                    self.db.indexer.add_text((self.classname, newid, key),
                        value)

            elif isinstance(prop, Password):
                if not isinstance(value, password.Password):
                    raise TypeError('new property "%s" not a Password'%key)

            elif isinstance(prop, Date):
                if value is not None and not isinstance(value, date.Date):
                    raise TypeError('new property "%s" not a Date'%key)

            elif isinstance(prop, Interval):
                if value is not None and not isinstance(value, date.Interval):
                    raise TypeError('new property "%s" not an Interval'%key)

            elif value is not None and isinstance(prop, Number):
                try:
                    float(value)
                except ValueError:
                    raise TypeError('new property "%s" not numeric'%key)

            elif value is not None and isinstance(prop, Integer):
                try:
                    int(value)
                except ValueError:
                    raise TypeError('new property "%s" not integer'%key)

            elif value is not None and isinstance(prop, Boolean):
                try:
                    int(value)
                except ValueError:
                    raise TypeError('new property "%s" not boolean'%key)

        # make sure there's data where there needs to be
        for key, prop in self.properties.items():
            if key in propvalues:
                continue
            if key == self.key:
                raise ValueError('key property "%s" is required'%key)
            if isinstance(prop, Multilink):
                propvalues[key] = []
            else:
                propvalues[key] = None

        # done
        self.db.addnode(self.classname, newid, propvalues)
        if self.do_journal:
            self.db.addjournal(self.classname, newid, ''"create", {})

        # XXX numeric ids
        return str(newid)

    def get(self, nodeid, propname, default=_marker, cache=1):
        """Get the value of a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.  'propname' must be the name of a property
        of this class or a KeyError is raised.

        'cache' exists for backwards compatibility, and is not used.
        """
        if propname == 'id':
            return nodeid

        # get the node's dict
        d = self.db.getnode(self.classname, nodeid, fetch_multilinks=False)
        # handle common case -- that property is in dict -- first
        # if None and one of creator/creation actor/activity return None
        if propname in d:
            r = d [propname]
            # return copy of our list
            if isinstance (r, list):
                return r[:]
            if r is not None:
                return r
            elif propname in ('creation', 'activity', 'creator', 'actor'):
                return r

        # propname not in d:
        if propname == 'creation' or propname == 'activity':
            return date.Date()
        if propname == 'creator' or propname == 'actor':
            return self.db.getuid()

        # get the property (raises KeyError if invalid)
        prop = self.properties[propname]

        # lazy evaluation of Multilink
        if propname not in d and isinstance(prop, Multilink):
            self.db._materialize_multilink(self.classname, nodeid, d, propname)

        # handle there being no value in the table for the property
        if propname not in d or d[propname] is None:
            if default is _marker:
                if isinstance(prop, Multilink):
                    return []
                else:
                    return None
            else:
                return default

        # don't pass our list to other code
        if isinstance(prop, Multilink):
            return d[propname][:]

        return d[propname]

    def set(self, nodeid, **propvalues):
        """Modify a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.

        Each key in 'propvalues' must be the name of a property of this
        class or a KeyError is raised.

        All values in 'propvalues' must be acceptable types for their
        corresponding properties or a TypeError is raised.

        If the value of the key property is set, it must not collide with
        other key strings or a ValueError is raised.

        If the value of a Link or Multilink property contains an invalid
        node id, a ValueError is raised.
        """
        self.fireAuditors('set', nodeid, propvalues)
        oldvalues = copy.deepcopy(self.db.getnode(self.classname, nodeid))
        propvalues = self.set_inner(nodeid, **propvalues)
        self.fireReactors('set', nodeid, oldvalues)
        return propvalues

    def set_inner(self, nodeid, **propvalues):
        """ Called by set, in-between the audit and react calls.
        """
        if not propvalues:
            return propvalues

        if ('creator' in propvalues or 'actor' in propvalues or 
             'creation' in propvalues or 'activity' in propvalues):
            raise KeyError('"creator", "actor", "creation" and '
                '"activity" are reserved')

        if 'id' in propvalues:
            raise KeyError('"id" is reserved')

        for p in propvalues:
            prop = self.properties[p]
            if prop.computed:
                raise KeyError('"%s" is a computed property'%p)

        if self.db.journaltag is None:
            raise DatabaseError(_('Database open read-only'))

        node = self.db.getnode(self.classname, nodeid)
        if self.is_retired(nodeid):
            raise IndexError('Requested item is retired')
        num_re = re.compile(r'^\d+$')

        # make a copy of the values dictionary - we'll modify the contents
        propvalues = propvalues.copy()

        # if the journal value is to be different, store it in here
        journalvalues = {}

        # remember the add/remove stuff for multilinks, making it easier
        # for the Database layer to do its stuff
        multilink_changes = {}

        # omit quiet properties from history/changelog
        quiet_props = []

        for propname, value in list(propvalues.items()):
            # check to make sure we're not duplicating an existing key
            if propname == self.key and node[propname] != value:
                try:
                    self.lookup(value)
                except KeyError:
                    pass
                else:
                    raise ValueError('node with key "%s" exists'%value)

            # this will raise the KeyError if the property isn't valid
            # ... we don't use getprops() here because we only care about
            # the writeable properties.
            try:
                prop = self.properties[propname]
            except KeyError:
                raise KeyError('"%s" has no property named "%s"'%(
                    self.classname, propname))

            # if the value's the same as the existing value, no sense in
            # doing anything
            current = node.get(propname, None)
            if value == current:
                del propvalues[propname]
                continue
            journalvalues[propname] = current

            # do stuff based on the prop type
            if isinstance(prop, Link):
                link_class = prop.classname
                # if it isn't a number, it's a key
                if value is not None and not isinstance(value, type('')):
                    raise ValueError('property "%s" link value be a string'%(
                        propname))
                if isinstance(value, type('')) and not num_re.match(value):
                    try:
                        value = self.db.classes[link_class].lookup(value)
                    except (TypeError, KeyError):
                        raise IndexError('new property "%s": %s not a %s'%(
                            propname, value, prop.classname))

                if (value is not None and
                        not self.db.getclass(link_class).hasnode(value)):
                    raise IndexError('%s has no node %s'%(link_class,
                        value))

                if self.do_journal and prop.do_journal:
                    # register the unlink with the old linked node
                    if node[propname] is not None:
                        self.db.addjournal(link_class, node[propname],
                            ''"unlink", (self.classname, nodeid, propname))

                    # register the link with the newly linked node
                    if value is not None:
                        self.db.addjournal(link_class, value, ''"link",
                            (self.classname, nodeid, propname))

            elif isinstance(prop, Multilink):
                if value is None:
                    value = []
                if not hasattr(value, '__iter__') or type(value) == type(''):
                    raise TypeError('new property "%s" not an iterable of'
                        ' ids'%propname)
                link_class = self.properties[propname].classname
                l = []
                for entry in value:
                    # if it isn't a number, it's a key
                    if type(entry) != type(''):
                        raise ValueError('new property "%s" link value '
                            'must be a string'%propname)
                    if not num_re.match(entry):
                        try:
                            entry = self.db.classes[link_class].lookup(entry)
                        except (TypeError, KeyError):
                            raise IndexError('new property "%s": %s not a %s'%(
                                propname, entry,
                                self.properties[propname].classname))
                    l.append(entry)
                value = l
                propvalues[propname] = value

                # figure the journal entry for this property
                add = []
                remove = []

                # handle removals
                if propname in node:
                    l = node[propname]
                else:
                    l = []
                for id in l[:]:
                    if id in value:
                        continue
                    # register the unlink with the old linked node
                    if self.do_journal and self.properties[propname].do_journal:
                        self.db.addjournal(link_class, id, 'unlink',
                            (self.classname, nodeid, propname))
                    l.remove(id)
                    remove.append(id)

                # handle additions
                for id in value:
                    if id in l:
                        continue
                    # We can safely check this condition after
                    # checking that this is an addition to the
                    # multilink since the condition was checked for
                    # existing entries at the point they were added to
                    # the multilink.  Since the hasnode call will
                    # result in a SQL query, it is more efficient to
                    # avoid the check if possible.
                    if not self.db.getclass(link_class).hasnode(id):
                        raise IndexError('%s has no node %s'%(link_class,
                            id))
                    # register the link with the newly linked node
                    if self.do_journal and self.properties[propname].do_journal:
                        self.db.addjournal(link_class, id, 'link',
                            (self.classname, nodeid, propname))
                    l.append(id)
                    add.append(id)

                # figure the journal entry
                l = []
                if add:
                    l.append(('+', add))
                if remove:
                    l.append(('-', remove))
                multilink_changes[propname] = (add, remove)
                if l:
                    journalvalues[propname] = tuple(l)

            elif isinstance(prop, String):
                if value is not None and type(value) != type('') and type(value) != type(u''):
                    raise TypeError('new property "%s" not a string'%propname)
                if prop.indexme:
                    if value is None: value = ''
                    self.db.indexer.add_text((self.classname, nodeid, propname),
                        value)

            elif isinstance(prop, Password):
                if not isinstance(value, password.Password):
                    raise TypeError('new property "%s" not a Password'%propname)
                propvalues[propname] = value
                journalvalues[propname] = \
                    current and password.JournalPassword(current)

            elif value is not None and isinstance(prop, Date):
                if not isinstance(value, date.Date):
                    raise TypeError('new property "%s" not a Date'% propname)
                propvalues[propname] = value

            elif value is not None and isinstance(prop, Interval):
                if not isinstance(value, date.Interval):
                    raise TypeError('new property "%s" not an '
                        'Interval'%propname)
                propvalues[propname] = value

            elif value is not None and isinstance(prop, Number):
                try:
                    float(value)
                except ValueError:
                    raise TypeError('new property "%s" not numeric'%propname)

            elif value is not None and isinstance(prop, Integer):
                try:
                    int(value)
                except ValueError:
                    raise TypeError('new property "%s" not integer'%propname)

            elif value is not None and isinstance(prop, Boolean):
                try:
                    int(value)
                except ValueError:
                    raise TypeError('new property "%s" not boolean'%propname)

            # record quiet properties to omit from history/changelog
            if prop.quiet:
                quiet_props.append(propname)

        # nothing to do?
        if not propvalues:
            return propvalues

        # update the activity time
        propvalues['activity'] = date.Date()
        propvalues['actor'] = self.db.getuid()

        # do the set
        self.db.setnode(self.classname, nodeid, propvalues, multilink_changes)

        # remove the activity props now they're handled
        del propvalues['activity']
        del propvalues['actor']

        # journal the set
        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, ''"set", journalvalues)

        # remove quiet properties from output
        for propname in quiet_props:
            if propname in propvalues:
                del propvalues[propname]

        return propvalues

    def retire(self, nodeid):
        """Retire a node.

        The properties on the node remain available from the get() method,
        and the node's id is never reused.

        Retired nodes are not returned by the find(), list(), or lookup()
        methods, and other nodes may reuse the values of their key properties.
        """
        if self.db.journaltag is None:
            raise DatabaseError(_('Database open read-only'))

        self.fireAuditors('retire', nodeid, None)

        # use the arg for __retired__ to cope with any odd database type
        # conversion (hello, sqlite)
        sql = 'update _%s set __retired__=%s where id=%s'%(self.classname,
            self.db.arg, self.db.arg)
        self.db.sql(sql, (nodeid, nodeid))
        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, ''"retired", None)

        self.fireReactors('retire', nodeid, None)

    def restore(self, nodeid):
        """Restore a retired node.

        Make node available for all operations like it was before retirement.
        """
        if self.db.journaltag is None:
            raise DatabaseError(_('Database open read-only'))

        node = self.db.getnode(self.classname, nodeid)
        # check if key property was overrided
        key = self.getkey()
        try:
            id = self.lookup(node[key])
        except KeyError:
            pass
        else:
            raise KeyError("Key property (%s) of retired node clashes "
                "with existing one (%s)" % (key, node[key]))

        self.fireAuditors('restore', nodeid, None)
        # use the arg for __retired__ to cope with any odd database type
        # conversion (hello, sqlite)
        sql = 'update _%s set __retired__=%s where id=%s'%(self.classname,
            self.db.arg, self.db.arg)
        self.db.sql(sql, (0, nodeid))
        if self.do_journal:
            self.db.addjournal(self.classname, nodeid, ''"restored", None)

        self.fireReactors('restore', nodeid, None)

    def is_retired(self, nodeid):
        """Return true if the node is rerired
        """
        sql = 'select __retired__ from _%s where id=%s'%(self.classname,
            self.db.arg)
        self.db.sql(sql, (nodeid,))
        return int(self.db.sql_fetchone()[0]) > 0

    def destroy(self, nodeid):
        """Destroy a node.

        WARNING: this method should never be used except in extremely rare
                 situations where there could never be links to the node being
                 deleted

        WARNING: use retire() instead

        WARNING: the properties of this node will not be available ever again

        WARNING: really, use retire() instead

        Well, I think that's enough warnings. This method exists mostly to
        support the session storage of the cgi interface.

        The node is completely removed from the hyperdb, including all journal
        entries. It will no longer be available, and will generally break code
        if there are any references to the node.
        """
        if self.db.journaltag is None:
            raise DatabaseError(_('Database open read-only'))
        self.db.destroynode(self.classname, nodeid)

    # Locating nodes:
    def hasnode(self, nodeid):
        """Determine if the given nodeid actually exists
        """
        return self.db.hasnode(self.classname, nodeid)

    def setkey(self, propname):
        """Select a String property of this class to be the key property.

        'propname' must be the name of a String property of this class or
        None, or a TypeError is raised.  The values of the key property on
        all existing nodes must be unique or a ValueError is raised.
        """
        prop = self.getprops()[propname]
        if not isinstance(prop, String):
            raise TypeError('key properties must be String')
        self.key = propname

    def getkey(self):
        """Return the name of the key property for this class or None."""
        return self.key

    def lookup(self, keyvalue):
        """Locate a particular node by its key property and return its id.

        If this class has no key property, a TypeError is raised.  If the
        'keyvalue' matches one of the values for the key property among
        the nodes in this class, the matching node's id is returned;
        otherwise a KeyError is raised.
        """
        if not self.key:
            raise TypeError('No key property set for class %s'%self.classname)

        # use the arg to handle any odd database type conversion (hello,
        # sqlite)
        sql = "select id from _%s where _%s=%s and __retired__=%s"%(
            self.classname, self.key, self.db.arg, self.db.arg)
        self.db.sql(sql, (str(keyvalue), 0))

        # see if there was a result that's not retired
        row = self.db.sql_fetchone()
        if not row:
            raise KeyError('No key (%s) value "%s" for "%s"'%(self.key,
                keyvalue, self.classname))

        # return the id
        # XXX numeric ids
        return str(row[0])

    def find(self, **propspec):
        """Get the ids of nodes in this class which link to the given nodes.

        'propspec' consists of keyword args propname=nodeid or
                   propname={nodeid:1, }
        'propname' must be the name of a property in this class, or a
                   KeyError is raised.  That property must be a Link or
                   Multilink property, or a TypeError is raised.

        Any node in this class whose 'propname' property links to any of
        the nodeids will be returned. Examples::

            db.issue.find(messages='1')
            db.issue.find(messages={'1':1,'3':1}, files={'7':1})
        """
        # shortcut
        if not propspec:
            return []

        # validate the args
        props = self.getprops()
        for propname, nodeids in propspec.items():
            # check the prop is OK
            prop = props[propname]
            if not isinstance(prop, Link) and not isinstance(prop, Multilink):
                raise TypeError("'%s' not a Link/Multilink property"%propname)

        # first, links
        a = self.db.arg
        allvalues = ()
        sql = []
        where = []
        for prop, values in propspec.items():
            if not isinstance(props[prop], hyperdb.Link):
                continue
            if type(values) is type({}) and len(values) == 1:
                values = list(values)[0]
            if type(values) is type(''):
                allvalues += (values,)
                where.append('_%s = %s'%(prop, a))
            elif values is None:
                where.append('_%s is NULL'%prop)
            else:
                values = list(values)
                s = ''
                if None in values:
                    values.remove(None)
                    s = '_%s is NULL or '%prop
                allvalues += tuple(values)
                s += '_%s in (%s)'%(prop, ','.join([a]*len(values)))
                where.append('(' + s +')')
        if where:
            allvalues = (0, ) + allvalues
            sql.append("""select id from _%s where  __retired__=%s
                and %s"""%(self.classname, a, ' and '.join(where)))

        # now multilinks
        for prop, values in propspec.items():
            p = props[prop]
            if not isinstance(p, hyperdb.Multilink):
                continue
            if not values:
                continue
            allvalues += (0, )
            tn = p.table_name
            ln = p.linkid_name
            nn = p.nodeid_name
            cn = '_' + self.classname
            ret = ''
            dis = ''
            ord = ''
            if p.rev_property:
                if isinstance(p.rev_property, Link):
                    ret = 'and %s.__retired__=%s ' % (tn, a)
                    allvalues += (0, )
                dis = 'distinct '
                ord = ' order by %s.id' % cn
            if type(values) is type(''):
                allvalues += (values,)
                s = a
            else:
                allvalues += tuple(values)
                s = ','.join([a]*len(values))
            sql.append("""select %s%s.id from %s, %s where  %s.__retired__=%s
                  %sand %s.id = %s.%s and %s.%s in (%s)%s"""%(dis, cn, cn,
                  tn, cn, a, ret, cn, tn, nn, tn, ln, s, ord))

        if not sql:
            return []
        sql = ' union '.join(sql)
        self.db.sql(sql, allvalues)
        # XXX numeric ids
        l = [str(x[0]) for x in self.db.sql_fetchall()]
        return l

    def stringFind(self, **requirements):
        """Locate a particular node by matching a set of its String
        properties in a caseless search.

        If the property is not a String property, a TypeError is raised.

        The return is a list of the id of all nodes that match.
        """
        where = []
        args = []
        for propname in requirements:
            prop = self.properties[propname]
            if not isinstance(prop, String):
                raise TypeError("'%s' not a String property"%propname)
            where.append(propname)
            args.append(requirements[propname].lower())

        # generate the where clause
        s = ' and '.join(['lower(_%s)=%s'%(col, self.db.arg) for col in where])
        sql = 'select id from _%s where %s and __retired__=%s'%(
            self.classname, s, self.db.arg)
        args.append(0)
        self.db.sql(sql, tuple(args))
        # XXX numeric ids
        l = [str(x[0]) for x in self.db.sql_fetchall()]
        return l

    def list(self):
        """ Return a list of the ids of the active nodes in this class.
        """
        return self.getnodeids(retired=0)

    def getnodeids(self, retired=None):
        """ Retrieve all the ids of the nodes for a particular Class.

            Set retired=None to get all nodes. Otherwise it'll get all the
            retired or non-retired nodes, depending on the flag.
        """
        # flip the sense of the 'retired' flag if we don't want all of them
        if retired is not None:
            args = (0, )
            if retired:
                compare = '>'
            else:
                compare = '='
            sql = 'select id from _%s where __retired__%s%s'%(self.classname,
                compare, self.db.arg)
        else:
            args = ()
            sql = 'select id from _%s'%self.classname
        self.db.sql(sql, args)
        # XXX numeric ids
        ids = [str(x[0]) for x in self.db.cursor.fetchall()]
        return ids

    def _subselect(self, proptree, parentname=None):
        """Create a subselect. This is factored out because some
           databases (hmm only one, so far) doesn't support subselects
           look for "I can't believe it's not a toy RDBMS" in the mysql
           backend.
        """
        multilink_table = proptree.propclass.table_name
        nodeid_name     = proptree.propclass.nodeid_name
        linkid_name     = proptree.propclass.linkid_name
        if parentname is None:
            parentname = '_' + proptree.parent.classname

        w = ''
        if proptree.need_retired:
            w = ' where %s.__retired__=0'%(multilink_table)
        if proptree.need_child_retired:
            tn1 = multilink_table
            tn2 = '_' + proptree.classname
            w = ', %s where %s.%s=%s.id and %s.__retired__=0'%(tn2,
                tn1, linkid_name, tn2, tn2)
        return '%s.id not in (select %s from %s%s)'%(parentname, nodeid_name,
            multilink_table, w)

    def _filter_multilink_expression_fallback(self, proptree, expr):
        '''This is a fallback for database that do not support
           subselects.'''
        classname = proptree.parent.uniqname
        multilink_table = proptree.propclass.table_name
        nid = proptree.propclass.nodeid_name
        lid = proptree.propclass.linkid_name

        is_valid = expr.evaluate

        last_id, kws = None, []

        ids = IdListOptimizer()
        append = ids.append

        # This join and the evaluation in program space
        # can be expensive for larger databases!
        # TODO: Find a faster way to collect the data needed
        # to evalute the expression.
        # Moving the expression evaluation into the database
        # would be nice but this tricky: Think about the cases
        # where the multilink table does not have join values
        # needed in evaluation.
        w = j = ''
        s = 'm.%s' % lid
        if proptree.need_retired:
            w = ' and m.__retired__=0'
        elif proptree.need_child_retired:
            tn2 = '_' + proptree.classname
            j = ' LEFT OUTER JOIN %s ON %s.id = m.%s' % (tn2, tn2, lid)
            w = ' and %s.__retired__=0'%(tn2)
            s = '%s.id' % tn2

        stmnt = "SELECT c.id, %s FROM _%s as c " \
                "LEFT OUTER JOIN %s as m " \
                "ON c.id = m.%s%s%s ORDER BY c.id" % (
                    s, classname, multilink_table, nid, j, w)
        self.db.sql(stmnt)

        # collect all multilink items for a class item
        for nodeid, kw in self.db.sql_fetchiter():
            if nodeid != last_id:
                if last_id is None:
                    last_id = nodeid
                else:
                    # we have all multilink items -> evaluate!
                    if is_valid(kws): append(last_id)
                    last_id, kws = nodeid, []
            if kw is not None:
                kws.append(int(kw))

        if last_id is not None and is_valid(kws): 
            append(last_id)

        # we have ids of the classname table
        return ids.where("_%s.id" % classname, self.db.arg)

    def _filter_link_expression(self, proptree, v):
        """ Filter elements in the table that match the given expression
        """
        pln = proptree.parent.uniqname
        prp = proptree.name
        try:
            opcodes = [int(x) for x in v]
            if min(opcodes) >= -1:
                raise ValueError()
            expr = compile_expression(opcodes)
            # NULL doesn't compare to NULL in SQL
            # So not (x = '1') will *not* include NULL values for x
            # That's why we need that and clause:
            atom = "_%s._%s = %s and _%s._%s is not NULL" % (
                pln, prp, self.db.arg, pln, prp)
            atom_nil = "_%s._%s is NULL" % (pln, prp)
            lambda_atom = lambda n: atom if n.x >= 0 else atom_nil
            values = []
            w = expr.generate(lambda_atom)
            def collect_values(n):
                if n.x >= 0:
                    values.append(n.x)
            expr.visit(collect_values)
            return w, values
        except:
            pass
        # Fallback to original code
        args = []
        where = None
        d = {}
        for entry in v:
            if entry == '-1':
                entry = None
            d[entry] = entry
        l = []
        if None in d or not d:
            if None in d: del d[None]
            l.append('_%s._%s is NULL'%(pln, prp))
        if d:
            v = list(d)
            s = ','.join([self.db.arg for x in v])
            l.append('(_%s._%s in (%s))'%(pln, prp, s))
            args = v
        if l:
            where = '(' + ' or '.join(l) +')'
        return where, args

    def _filter_multilink_expression(self, proptree, v):
        """ Filters out elements of the classname table that do not
            match the given expression.
            Returns tuple of 'WHERE' introns for the overall filter.
        """
        classname = proptree.parent.uniqname
        multilink_table = proptree.propclass.table_name
        nid = proptree.propclass.nodeid_name
        lid = proptree.propclass.linkid_name

        try:
            opcodes = [int(x) for x in v]
            if min(opcodes) >= -1:
                raise ValueError()

            expr = compile_expression(opcodes)

            if not self.supports_subselects:
                # We heavily rely on subselects. If there is
                # no decent support fall back to slower variant.
                return self._filter_multilink_expression_fallback(
                    proptree, expr)

            w = j = ''
            if proptree.need_retired:
                w = ' and %s.__retired__=0'%(multilink_table)
            elif proptree.need_child_retired:
                tn1 = multilink_table
                tn2 = '_' + proptree.classname
                j = ', %s' % tn2
                w = ' and %s.%s=%s.id and %s.__retired__=0'%(tn1, lid, tn2, tn2)

            atom = \
                "%s IN(SELECT %s FROM %s%s WHERE %s=a.id%s)" % (
                self.db.arg, lid, multilink_table, j, nid, w)
            atom_nil = self._subselect(proptree, 'a')

            lambda_atom = lambda n: atom if n.x >= 0 else atom_nil

            intron = \
                "_%(classname)s.id in (SELECT id " \
                "FROM _%(classname)s AS a WHERE %(condition)s) " % {
                    'classname' : classname,
                    'condition' : expr.generate(lambda_atom) }

            values = []
            def collect_values(n):
                if n.x >= 0:
                    values.append(n.x)
            expr.visit(collect_values)

            return intron, values
        except:
            # fallback behavior when expression parsing above fails
            orclause = ''
            if '-1' in v :
                v = [x for x in v if int (x) > 0]
                orclause = self._subselect(proptree)
            where = []
            where.append("%s.%s in (%s)" % (multilink_table, lid,
                ','.join([self.db.arg] * len(v))))
            where.append('_%s.id=%s.%s'%(classname, multilink_table, nid))
            where = ' and '.join (where)
            if orclause :
                where = '((' + ' or '.join ((where + ')', orclause)) + ')'

            return where, v

    def _filter_sql (self, search_matches, filterspec, srt=[], grp=[], retr=0,
                     retired=False, exact_match_spec={}, limit=None,
                     offset=None):
        """ Compute the proptree and the SQL/ARGS for a filter.
        For argument description see filter below.
        We return a 3-tuple, the proptree, the sql and the sql-args
        or None if no SQL is necessary.
        The flag retr serves to retrieve *all* non-Multilink properties
        (for filling the cache during a filter_iter)
        """
        # we can't match anything if search_matches is empty
        if not search_matches and search_matches is not None:
            return None

        icn = self.classname

        # vars to hold the components of the SQL statement
        frum = []       # FROM clauses
        loj = []        # LEFT OUTER JOIN clauses
        where = []      # WHERE clauses
        args = []       # *any* positional arguments
        a = self.db.arg

        # figure the WHERE clause from the filterspec
        use_distinct = False  # Do we need a distinct clause?
        sortattr = self._sortattr (group = grp, sort = srt)
        proptree = self._proptree(filterspec, exact_match_spec, sortattr, retr)
        mlseen = 0
        for pt in reversed(proptree.sortattr):
            p = pt
            while p.parent:
                if isinstance (p.propclass, Multilink):
                    mlseen = True
                if mlseen:
                    p.sort_ids_needed = True
                    p.tree_sort_done = False
                p = p.parent
            if not mlseen:
                pt.attr_sort_done = pt.tree_sort_done = True
        proptree.compute_sort_done()

        cols = ['_%s.id'%icn]
        mlsort = []
        rhsnum = 0
        for p in proptree:
            rc = ac = oc = None
            cn = p.classname
            ln = p.uniqname
            pln = p.parent.uniqname
            pcn = p.parent.classname
            k = p.name
            v = p.val
            propclass = p.propclass
            if p.parent == proptree and p.name == 'id' \
                and 'retrieve' in p.need_for:
                p.sql_idx = 0
            if 'sort' in p.need_for or 'retrieve' in p.need_for:
                rc = oc = ac = '_%s._%s'%(pln, k)
            if isinstance(propclass, Multilink):
                if 'search' in p.need_for:
                    # if we joining with Multilink tables we need distinct
                    use_distinct = True
                    tn = propclass.table_name
                    nid = propclass.nodeid_name
                    lid = propclass.linkid_name
                    frum.append(tn)
                    if p.children or p.need_child_retired:
                        frum.append('_%s as _%s' % (cn, ln))
                        where.append('%s.%s=_%s.id'%(tn, lid, ln))
                        if p.need_child_retired:
                            where.append('_%s.__retired__=0'%(ln))
                    # Note: need the where-clause if p has
                    # children that compute additional restrictions
                    if  (not p.has_values
                         or (not isinstance(v, type([])) and v != '-1')
                         or p.children):
                        where.append('_%s.id=%s.%s'%(pln, tn, nid))
                    if v in ('-1', ['-1'], []):
                        # only match rows that have count(linkid)=0 in the
                        # corresponding multilink table)
                        where.append(self._subselect(p))
                    else:
                        if p.has_values:
                            if isinstance(v, type([])):
                                # The where-clause above is conditionally
                                # created in _filter_multilink_expression
                                w, arg = self._filter_multilink_expression(p, v)
                                where.append(w)
                                args += arg
                            else:
                                where.append('%s.%s=%s'%(tn, lid, a))
                                args.append(v)
                        # Don't match retired nodes if rev_multilink
                        if p.need_retired:
                            where.append('%s.__retired__=0'%(tn))
                if 'sort' in p.need_for:
                    assert not p.attr_sort_done and not p.sort_ids_needed
            elif k == 'id':
                if 'search' in p.need_for:
                    if isinstance(v, type([])):
                        # If there are no permitted values, then the
                        # where clause will always be false, and we
                        # can optimize the query away.
                        if not v:
                            return None
                        s = ','.join([a for x in v])
                        where.append('_%s.%s in (%s)'%(pln, k, s))
                        args = args + v
                    else:
                        where.append('_%s.%s=%s'%(pln, k, a))
                        args.append(v)
                if 'sort' in p.need_for or 'retrieve' in p.need_for:
                    rc = oc = ac = '_%s.id'%pln
            elif isinstance(propclass, String):
                if 'search' in p.need_for:
                    exact = []
                    if not isinstance(v, type([])):
                        v = [v]
                    new_v = []
                    for x in v:
                        if isinstance(x, hyperdb.Exact_Match):
                            exact.append(True)
                            new_v.append(x.value)
                        else:
                            exact.append(False)
                            # Quote special search characters '%' and '_' for
                            # correct matching with LIKE/ILIKE
                            # Note that we now pass the elements of v as query
                            # arguments and don't interpolate the quoted string
                            # into the sql statement. Should be safer.
                            new_v.append(self.db.search_stringquote(x))
                    v = new_v

                    # now add to the where clause
                    w = []
                    for vv, ex in zip(v, exact):
                        if ex:
                            w.append("_%s._%s %s %s"%(
                                pln, k, self.case_sensitive_equal, a))
                            args.append(vv)
                        else:
                            w.append("_%s._%s %s %s ESCAPE %s"%(
                                pln, k, self.case_insensitive_like, a, a))
                            args.extend((vv, '\\'))
                    where.append ('(' + ' and '.join(w) + ')')
                if 'sort' in p.need_for:
                    oc = ac = 'lower(_%s._%s)'%(pln, k)
            elif isinstance(propclass, Link):
                if 'search' in p.need_for:
                    if p.children:
                        if 'sort' not in p.need_for:
                            frum.append('_%s as _%s' % (cn, ln))
                        c = [x for x in p.children if 'search' in x.need_for]
                        if c:
                            where.append('_%s._%s=_%s.id'%(pln, k, ln))
                    if p.has_values:
                        if isinstance(v, type([])):
                            w, arg = self._filter_link_expression(p, v)
                            if w:
                                where.append(w)
                                args += arg
                        else:
                            if v in ('-1', None):
                                v = None
                                where.append('_%s._%s is NULL'%(pln, k))
                            else:
                                where.append('_%s._%s=%s'%(pln, k, a))
                                args.append(v)
                if 'sort' in p.need_for:
                    lp = p.cls.labelprop()
                    oc = ac = '_%s._%s'%(pln, k)
                    if lp != 'id':
                        if p.tree_sort_done:
                            loj.append(
                                'LEFT OUTER JOIN _%s as _%s on _%s._%s=_%s.id'%(
                                cn, ln, pln, k, ln))
                        oc = '_%s._%s'%(ln, lp)
                if 'retrieve' in p.need_for:
                    rc = '_%s._%s'%(pln, k)
            elif isinstance(propclass, Date) and 'search' in p.need_for:
                dc = self.db.to_sql_value(hyperdb.Date)
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s._%s in (%s)'%(pln, k, s))
                    args = args + [dc(date.Date(x)) for x in v]
                else:
                    try:
                        wh = []
                        ar = []
                        for d in v.split(','):
                            w1 = []
                            if d == '-':
                                wh.append('_%s._%s is NULL'%(pln, k))
                                continue
                            # Try to filter on range of dates
                            date_rng = propclass.range_from_raw(d, self.db)
                            if date_rng.from_value:
                                w1.append('_%s._%s >= %s'%(pln, k, a))
                                ar.append(dc(date_rng.from_value))
                            if date_rng.to_value:
                                w1.append('_%s._%s <= %s'%(pln, k, a))
                                ar.append(dc(date_rng.to_value))
                            wh.append (' and '.join (w1))
                        where.append ('(' + ' or '.join (wh) + ')')
                        args.extend (ar)
                    except ValueError:
                        # If range creation fails - ignore that search parameter
                        pass
            elif isinstance(propclass, Interval):
                # filter/sort using the __<prop>_int__ column
                if 'search' in p.need_for:
                    if isinstance(v, type([])):
                        s = ','.join([a for x in v])
                        where.append('_%s.__%s_int__ in (%s)'%(pln, k, s))
                        args = args + [date.Interval(x).as_seconds() for x in v]
                    else:
                        try:
                            # Try to filter on range of intervals
                            date_rng = Range(v, date.Interval)
                            if date_rng.from_value:
                                where.append('_%s.__%s_int__ >= %s'%(pln, k, a))
                                args.append(date_rng.from_value.as_seconds())
                            if date_rng.to_value:
                                where.append('_%s.__%s_int__ <= %s'%(pln, k, a))
                                args.append(date_rng.to_value.as_seconds())
                        except ValueError:
                            # If range creation fails - ignore search parameter
                            pass
                if 'sort' in p.need_for:
                    oc = ac = '_%s.__%s_int__'%(pln,k)
                if 'retrieve' in p.need_for:
                    rc = '_%s._%s'%(pln,k)
            elif isinstance(propclass, Boolean) and 'search' in p.need_for:
                if type(v) == type(""):
                    v = v.split(',')
                if type(v) != type([]):
                    v = [v]
                bv = []
                for val in v:
                    if type(val) is type(''):
                        bv.append(propclass.from_raw (val))
                    else:
                        bv.append(bool(val))
                if len(bv) == 1:
                    where.append('_%s._%s=%s'%(pln, k, a))
                    args = args + bv
                else:
                    s = ','.join([a for x in v])
                    where.append('_%s._%s in (%s)'%(pln, k, s))
                    args = args + bv
            elif 'search' in p.need_for:
                if isinstance(v, type([])):
                    s = ','.join([a for x in v])
                    where.append('_%s._%s in (%s)'%(pln, k, s))
                    args = args + v
                else:
                    where.append('_%s._%s=%s'%(pln, k, a))
                    args.append(v)
            if oc:
                if p.sort_ids_needed:
                    if rc == ac:
                        p.sql_idx = len(cols)
                    p.auxcol = len(cols)
                    cols.append(ac)
                if p.tree_sort_done and p.sort_direction:
                    # Don't select top-level id or multilink twice
                    if (not p.sort_ids_needed or ac != oc) and (p.name != 'id'
                        or p.parent != proptree):
                        if rc == oc:
                            p.sql_idx = len(cols)
                        cols.append(oc)
                    desc = ['', ' desc'][p.sort_direction == '-']
                    # Some SQL dbs sort NULL values last -- we want them first.
                    if (self.order_by_null_values and p.name != 'id'):
                        nv = self.order_by_null_values % oc
                        cols.append(nv)
                        p.orderby.append(nv + desc)
                    p.orderby.append(oc + desc)
            if 'retrieve' in p.need_for and p.sql_idx is None:
                assert(rc)
                p.sql_idx = len(cols)
                cols.append (rc)

        props = self.getprops()

        # don't match retired nodes
        if retired is not None:
            op = '='
            if retired:
                op = '!='
            where.append('_%s.__retired__%s0'%(icn, op))

        # add results of full text search
        if search_matches is not None:
            s = ','.join([a for x in search_matches])
            where.append('_%s.id in (%s)'%(icn, s))
            args = args + [x for x in search_matches]

        # construct the SQL
        frum.append('_'+icn)
        frum = ','.join(frum)
        if where:
            where = ' where ' + (' and '.join(where))
        else:
            where = ''
        if use_distinct:
            # Avoid dupes
            cols[0] = 'distinct(_%s.id)'%icn

        order = []
        # keep correct sequence of order attributes.
        for sa in proptree.sortattr:
            if not sa.attr_sort_done:
                continue
            order.extend(sa.orderby)
        if order:
            order = ' order by %s'%(','.join(order))
        else:
            order = ''

        if limit is not None:
            limit = ' LIMIT %s' % limit
        else:
            limit = ''
        if offset is not None:
            offset = ' OFFSET %s' % offset
        else:
            offset = ''
        cols = ','.join(cols)
        loj = ' '.join(loj)
        sql = 'select %s from %s %s %s%s%s%s'%(
            cols, frum, loj, where, order, limit, offset)
        args = tuple(args)
        __traceback_info__ = (sql, args)
        return proptree, sql, args

    def filter(self, search_matches, filterspec, sort=[], group=[],
               retired=False, exact_match_spec={}, limit=None, offset=None):
        """Return a list of the ids of the active nodes in this class that
        match the 'filter' spec, sorted by the group spec and then the
        sort spec

        "filterspec" is {propname: value(s)}

        "sort" and "group" are [(dir, prop), ...] where dir is '+', '-'
        or None and prop is a prop name or None. Note that for
        backward-compatibility reasons a single (dir, prop) tuple is
        also allowed.

        "search_matches" is a container type or None

        The filter must match all properties specificed. If the property
        value to match is a list:

        1. String properties must match all elements in the list, and
        2. Other properties must match any of the elements in the list.
        """
        if __debug__:
            start_t = time.time()

        sq = self._filter_sql (search_matches, filterspec, sort, group,
                               retired=retired,
                               exact_match_spec=exact_match_spec,
                               limit=limit, offset=offset)
        # nothing to match?
        if sq is None:
            return []
        proptree, sql, args = sq

        cursor = self.db.sql_new_cursor(name='filter')
        self.db.sql(sql, args, cursor)
        # Reduce this to only the first row (the ID), this can save a
        # lot of space for large query results (not using fetchall)
        # We cannot do this if sorting by multilink
        if proptree.tree_sort_done:
            l = [str(row[0]) for row in cursor]
        else:
            l = cursor.fetchall()
        cursor.close()

        # Multilink sorting
        # Compute values needed for sorting in proptree.sort
        if not proptree.tree_sort_done:
            for p in proptree:
                if hasattr(p, 'auxcol'):
                    p.sort_ids = [row[p.auxcol] for row in l]
                    p.sort_result = p._sort_repr \
                        (p.propclass.sort_repr, p.sort_ids)
            l = proptree.sort ([str(row[0]) for row in l])

        if __debug__:
            self.db.stats['filtering'] += (time.time() - start_t)
        return l

    def filter_iter(self, search_matches, filterspec, sort=[], group=[],
                    retired=False, exact_match_spec={}, limit=None,
                    offset=None):
        """Iterator similar to filter above with same args.
        Limitation: We don't sort on multilinks.
        This uses an optimisation: We put all nodes that are in the
        current row into the node cache. Then we return the node id.
        That way a fetch of a node won't create another sql-fetch (with
        a join) from the database because the nodes are already in the
        cache. We're using our own temporary cursor.
        """
        sq = self._filter_sql(search_matches, filterspec, sort, group, retr=1,
                              retired=retired,
                              exact_match_spec=exact_match_spec,
                              limit=limit, offset=offset)
        # nothing to match?
        if sq is None:
            return
        proptree, sql, args = sq
        cursor = self.db.sql_new_cursor(name='filter_iter')
        self.db.sql(sql, args, cursor)
        classes = {}
        for p in proptree:
            if 'retrieve' in p.need_for:
                cn = p.parent.classname
                ptid = p.parent.id # not the nodeid!
                key = (cn, ptid)
                if key not in classes:
                    classes[key] = {}
                name = p.name
                assert (name)
                classes[key][name] = p
                p.to_hyperdb = self.db.to_hyperdb_value(p.propclass.__class__)
        while True:
            row = cursor.fetchone()
            if not row: break
            # populate cache with current items
            for (classname, ptid), pt in classes.items():
                nodeid = str(row[pt['id'].sql_idx])
                key = (classname, nodeid)
                if key in self.db.cache:
                    self.db._cache_refresh(key)
                    continue
                node = {}
                for propname, p in pt.items():
                    value = row[p.sql_idx]
                    if value is not None:
                        value = p.to_hyperdb(value)
                    node[propname] = value
                self.db._cache_save(key, node)
            yield str(row[0])
        cursor.close()

    def filter_sql(self, sql):
        """Return a list of the ids of the items in this class that match
        the SQL provided. The SQL is a complete "select" statement.

        The SQL select must include the item id as the first column.

        This function DOES NOT filter out retired items, add on a where
        clause "__retired__=0" if you don't want retired nodes.
        """
        if __debug__:
            start_t = time.time()

        self.db.sql(sql)
        l = self.db.sql_fetchall()

        if __debug__:
            self.db.stats['filtering'] += (time.time() - start_t)
        return l

    def count(self):
        """Get the number of nodes in this class.

        If the returned integer is 'numnodes', the ids of all the nodes
        in this class run from 1 to numnodes, and numnodes+1 will be the
        id of the next node to be created in this class.
        """
        return self.db.countnodes(self.classname)

    # Manipulating properties:
    def getprops(self, protected=1):
        """Return a dictionary mapping property names to property objects.
           If the "protected" flag is true, we include protected properties -
           those which may not be modified.
        """
        d = self.properties.copy()
        if protected:
            d['id'] = String()
            d['creation'] = hyperdb.Date()
            d['activity'] = hyperdb.Date()
            d['creator'] = hyperdb.Link('user')
            d['actor'] = hyperdb.Link('user')
        return d

    def addprop(self, **properties):
        """Add properties to this class.

        The keyword arguments in 'properties' must map names to property
        objects, or a TypeError is raised.  None of the keys in 'properties'
        may collide with the names of existing properties, or a ValueError
        is raised before any properties have been added.
        """
        for key in properties:
            if key in self.properties:
                raise ValueError(key)
        self.properties.update(properties)

    def index(self, nodeid):
        """Add (or refresh) the node to search indexes
        """
        # find all the String properties that have indexme
        for prop, propclass in self.getprops().items():
            if isinstance(propclass, String) and propclass.indexme:
                self.db.indexer.add_text((self.classname, nodeid, prop),
                    str(self.get(nodeid, prop)))

    #
    # import / export support
    #
    def export_list(self, propnames, nodeid):
        """ Export a node - generate a list of CSV-able data in the order
            specified by propnames for the given node.
        """
        properties = self.getprops()
        l = []
        for prop in propnames:
            proptype = properties[prop]
            value = self.get(nodeid, prop)
            # "marshal" data where needed
            if value is None:
                pass
            elif isinstance(proptype, hyperdb.Date):
                value = value.get_tuple()
            elif isinstance(proptype, hyperdb.Interval):
                value = value.get_tuple()
            elif isinstance(proptype, hyperdb.Password):
                value = str(value)
            l.append(repr_export(value))
        l.append(repr_export(self.is_retired(nodeid)))
        return l

    def import_list(self, propnames, proplist):
        """ Import a node - all information including "id" is present and
            should not be sanity checked. Triggers are not triggered. The
            journal should be initialised using the "creator" and "created"
            information.

            Return the nodeid of the node imported.
        """

        logger = logging.getLogger('roundup.hyperdb.backend')

        if self.db.journaltag is None:
            raise DatabaseError(_('Database open read-only'))
        properties = self.getprops()

        # make the new node's property map
        d = {}
        retire = 0
        if not "id" in propnames:
            newid = self.db.newid(self.classname)
        else:
            newid = eval_import(proplist[propnames.index("id")])
        for i in range(len(propnames)):
            # Use eval_import to reverse the repr_export() used to
            # output the CSV
            value = eval_import(proplist[i])

            # Figure the property for this column
            propname = propnames[i]

            # "unmarshal" where necessary
            if propname == 'id':
                continue
            elif propname == 'is retired':
                # is the item retired?
                if int(value):
                    retire = 1
                continue
            elif value is None:
                d[propname] = None
                continue

            prop = properties[propname]
            if value is None:
                # don't set Nones
                continue
            elif isinstance(prop, hyperdb.Date):
                value = date.Date(value)
            elif isinstance(prop, hyperdb.Interval):
                value = date.Interval(value)
            elif isinstance(prop, hyperdb.Password):
                value = password.Password(encrypted=value)
            elif isinstance(prop, String):
                value = us2s(value)
                if not isinstance(value, str):
                    raise TypeError('new property "%(propname)s" not a '
                        'string: %(value)r'%locals())
                if prop.indexme:
                    self.db.indexer.add_text((self.classname, newid, propname),
                        value)
            d[propname] = value

        # get a new id if necessary
        if newid is None:
            newid = self.db.newid(self.classname)

        activeid = None
        has_node = False

        # use the arg for __retired__ to cope with any odd database type
        # conversion (hello, sqlite)
        retired_sql = 'update _%s set __retired__=%s where id=%s'%(
            self.classname, self.db.arg, self.db.arg)

        # insert new node or update existing?
        # if integrity error raised try to recover
        try:
            has_node = self.hasnode(newid)
            if not has_node:
                self.db.addnode(self.classname, newid, d) # insert
            else:
                self.db.setnode(self.classname, newid, d) # update
            self.db.checkpoint_data()
        # Blech, different db's return different exceptions
        # so I can't list them here as some might not be defined
        # on a given system. So capture all exceptions from the
        # code above and try to correct it. If it's correctable its
        # some form of Uniqueness Failure/Integrity Error otherwise
        # undo the fixup and pass on the error.
        except Exception as e:  # nosec
            logger.info('Attempting to handle import exception '
                        'for id %s: %s' % (newid,e))

            keyname = self.db.user.getkey()
            if has_node or not keyname:  # Not an integrity error
                raise
            self.db.restore_connection_on_error()
            activeid = self.db.user.lookup(d[keyname])
            self.db.sql(retired_sql, (-1, activeid)) # clear the active node
            # this can only happen on an addnode, so retry
            try:
                # if this raises an error, let it propagate upward
                self.db.addnode(self.classname, newid, d) # insert
            except Exception:
                # undo the database change
                self.db.sql(retired_sql, (0, activeid)) # clear the active node
                raise # propagate
            logger.info('Successfully handled import exception '
                        'for id %s which conflicted with %s' % (
                            newid, activeid))

        # retire?
        if retire:
            self.db.sql(retired_sql, (newid, newid))

        if activeid:
            # unretire the active node
            self.db.sql(retired_sql, ('0', activeid))

        return newid

    def export_journals(self):
        """Export a class's journal - generate a list of lists of
        CSV-able data:

            nodeid, date, user, action, params

        No heading here - the columns are fixed.
        """
        properties = self.getprops()
        r = []
        for nodeid in self.getnodeids():
            for nodeid, date, user, action, params in self.history(nodeid,
                            enforceperm=False, skipquiet=False):
                date = date.get_tuple()
                if action == 'set':
                    export_data = {}
                    for propname, value in params.items():
                        if propname not in properties:
                            # property no longer in the schema
                            continue

                        prop = properties[propname]
                        # make sure the params are eval()'able
                        if value is None:
                            pass
                        elif isinstance(prop, Date):
                            value = value.get_tuple()
                        elif isinstance(prop, Interval):
                            value = value.get_tuple()
                        elif isinstance(prop, Password):
                            value = str(value)
                        export_data[propname] = value
                    params = export_data
                elif action == 'create' and params:
                    # old tracker with data stored in the create!
                    params = {}
                l = [nodeid, date, user, action, params]
                r.append(list(map(repr_export, l)))
        return r

class FileClass(hyperdb.FileClass, Class):
    """This class defines a large chunk of data. To support this, it has a
       mandatory String property "content" which is typically saved off
       externally to the hyperdb.

       The default MIME type of this data is defined by the
       "default_mime_type" class attribute, which may be overridden by each
       node if the class defines a "type" String property.
    """
    def __init__(self, db, classname, **properties):
        """The newly-created class automatically includes the "content"
        and "type" properties.
        """
        if 'content' not in properties:
            properties['content'] = hyperdb.String(indexme='yes')
        if 'type' not in properties:
            properties['type'] = hyperdb.String()
        Class.__init__(self, db, classname, **properties)

    def create(self, **propvalues):
        """ snaffle the file propvalue and store in a file
        """
        # we need to fire the auditors now, or the content property won't
        # be in propvalues for the auditors to play with
        self.fireAuditors('create', None, propvalues)

        # now remove the content property so it's not stored in the db
        content = propvalues['content']
        del propvalues['content']

        # do the database create
        newid = self.create_inner(**propvalues)

        # figure the mime type
        mime_type = propvalues.get('type', self.default_mime_type)

        # and index!
        if self.properties['content'].indexme:
            index_content = content
            if bytes != str and isinstance(content, bytes):
                index_content = content.decode('utf-8', errors='ignore')
            self.db.indexer.add_text((self.classname, newid, 'content'),
                index_content, mime_type)

        # store off the content as a file
        self.db.storefile(self.classname, newid, None, bs2b(content))

        # fire reactors
        self.fireReactors('create', newid, None)

        return newid

    def get(self, nodeid, propname, default=_marker, cache=1):
        """ Trap the content propname and get it from the file

        'cache' exists for backwards compatibility, and is not used.
        """
        poss_msg = 'Possibly a access right configuration problem.'
        if propname == 'content':
            try:
                return b2s(self.db.getfile(self.classname, nodeid, None))
            except IOError as strerror:
                # BUG: by catching this we donot see an error in the log.
                return 'ERROR reading file: %s%s\n%s\n%s'%(
                        self.classname, nodeid, poss_msg, strerror)
            except UnicodeDecodeError as e:
                # if content is not text (e.g. jpeg file) we get
                # unicode error trying to convert to string in python 3.
                # trap it and supply an error message. Include md5sum
                # of content as this string is included in the etag
                # calculation of the object.
                return ('%s%s is not text, retrieve using '
                        'binary_content property. mdsum: %s')%(self.classname,
                   nodeid, md5(self.db.getfile(self.classname, nodeid, None)).hexdigest())  # nosec - bandit md5 use ok
        elif propname == 'binary_content':
            return self.db.getfile(self.classname, nodeid, None)

        if default is not _marker:
            return Class.get(self, nodeid, propname, default)
        else:
            return Class.get(self, nodeid, propname)

    def set(self, itemid, **propvalues):
        """ Snarf the "content" propvalue and update it in a file
        """
        self.fireAuditors('set', itemid, propvalues)
        oldvalues = copy.deepcopy(self.db.getnode(self.classname, itemid))

        # now remove the content property so it's not stored in the db
        content = None
        if 'content' in propvalues:
            content = propvalues['content']
            del propvalues['content']

        # do the database create
        propvalues = self.set_inner(itemid, **propvalues)

        # do content?
        if content:
            # store and possibly index
            self.db.storefile(self.classname, itemid, None, bs2b(content))
            if self.properties['content'].indexme:
                mime_type = self.get(itemid, 'type', self.default_mime_type)
                index_content = content
                if bytes != str and isinstance(content, bytes):
                    index_content = content.decode('utf-8', errors='ignore')
                self.db.indexer.add_text((self.classname, itemid, 'content'),
                    index_content, mime_type)
            propvalues['content'] = content

        # fire reactors
        self.fireReactors('set', itemid, oldvalues)
        return propvalues

    def index(self, nodeid):
        """ Add (or refresh) the node to search indexes.

        Use the content-type property for the content property.
        """
        # find all the String properties that have indexme
        for prop, propclass in self.getprops().items():
            if prop == 'content' and propclass.indexme:
                mime_type = self.get(nodeid, 'type', self.default_mime_type)
                index_content = self.get(nodeid, 'binary_content')
                if bytes != str and isinstance(index_content, bytes):
                    index_content = index_content.decode('utf-8',
                                                         errors='ignore')
                self.db.indexer.add_text((self.classname, nodeid, 'content'),
                    index_content, mime_type)
            elif isinstance(propclass, hyperdb.String) and propclass.indexme:
                # index them under (classname, nodeid, property)
                try:
                    value = str(self.get(nodeid, prop))
                except IndexError:
                    # node has been destroyed
                    continue
                self.db.indexer.add_text((self.classname, nodeid, prop), value)

# XXX deviation from spec - was called ItemClass
class IssueClass(Class, roundupdb.IssueClass):
    # Overridden methods:
    def __init__(self, db, classname, **properties):
        """The newly-created class automatically includes the "messages",
        "files", "nosy", and "superseder" properties.  If the 'properties'
        dictionary attempts to specify any of these properties or a
        "creation", "creator", "activity" or "actor" property, a ValueError
        is raised.
        """
        if 'title' not in properties:
            properties['title'] = hyperdb.String(indexme='yes')
        if 'messages' not in properties:
            properties['messages'] = hyperdb.Multilink("msg")
        if 'files' not in properties:
            properties['files'] = hyperdb.Multilink("file")
        if 'nosy' not in properties:
            # note: journalling is turned off as it really just wastes
            # space. this behaviour may be overridden in an instance
            properties['nosy'] = hyperdb.Multilink("user", do_journal="no")
        if 'superseder' not in properties:
            properties['superseder'] = hyperdb.Multilink(classname)
        Class.__init__(self, db, classname, **properties)

# vim: set et sts=4 sw=4 :
