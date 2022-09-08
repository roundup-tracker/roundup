"""This module defines a very basic store that's used by the CGI interface
to store session and one-time-key information.

Yes, it's called "sessions" - because originally it only defined a session
class. It's now also used for One Time Key handling too.

We needed to split commits to session/OTK database from commits on the
main db structures (user data). This required two connections to the
sqlite db, which wasn't supported. This module was created so sqlite
didn't have to use dbm for the session/otk data. It hopefully will
provide a performance speedup.
"""
__docformat__ = 'restructuredtext'

from roundup.backends import sessions_rdbms


class BasicDatabase(sessions_rdbms.BasicDatabase):
    ''' Provide a nice encapsulation of an RDBMS table.

        Keys are id strings, values are automatically marshalled data.
    '''
    name = None

    def __init__(self, db):
        self.db = db
        self.conn, self.cursor = self.db.sql_open_connection(dbname=self.name)

        self.sql('''SELECT name FROM sqlite_master WHERE type='table' AND '''
                 '''name='%ss';''' % self.name)
        table_exists = self.cursor.fetchone()

        if not table_exists:
            # create table/rows etc.
            self.sql('''CREATE TABLE %(name)ss (%(name)s_key VARCHAR(255),
            %(name)s_value TEXT, %(name)s_time REAL)''' % {"name": self.name})
            self.sql('CREATE INDEX %(name)s_key_idx ON '
                     '%(name)ss(%(name)s_key)' % {"name": self.name})
            # Set journal mode to WAL.
            self.commit()  # close out rollback journal/transaction
            self.sql('pragma journal_mode=wal')  # set wal
            self.commit()  # close out rollback and commit wal change

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


class Sessions(BasicDatabase):
    name = 'session'


class OneTimeKeys(BasicDatabase):
    name = 'otk'

# vim: set et sts=4 sw=4 :
