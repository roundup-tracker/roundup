#$Id: sessions.py,v 1.7 2004-02-11 23:55:09 richard Exp $
"""This module defines a very basic store that's used by the CGI interface
to store session and one-time-key information.

Yes, it's called "sessions" - because originally it only defined a session
class. It's now also used for One Time Key handling too.
"""
__docformat__ = 'restructuredtext'

import anydbm, whichdb, os, marshal

class BasicDatabase:
    ''' Provide a nice encapsulation of an anydbm store.

        Keys are id strings, values are automatically marshalled data.
    '''
    _db_type = None

    def __init__(self, config):
        self.config = config
        self.dir = config.DATABASE
        # ensure files are group readable and writable
        os.umask(0002)

    def clear(self):
        path = os.path.join(self.dir, self.name)
        if os.path.exists(path):
            os.remove(path)
        elif os.path.exists(path+'.db'):    # dbm appends .db
            os.remove(path+'.db')

    def cache_db_type(self, path):
        ''' determine which DB wrote the class file, and cache it as an
            attribute of __class__ (to allow for subclassed DBs to be
            different sorts)
        '''
        db_type = ''
        if os.path.exists(path):
            db_type = whichdb.whichdb(path)
            if not db_type:
                raise hyperdb.DatabaseError, "Couldn't identify database type"
        elif os.path.exists(path+'.db'):
            # if the path ends in '.db', it's a dbm database, whether
            # anydbm says it's dbhash or not!
            db_type = 'dbm'
        self.__class__._db_type = db_type

    def get(self, infoid, value):
        db = self.opendb('c')
        try:
            if db.has_key(infoid):
                values = marshal.loads(db[infoid])
            else:
                return None
            return values.get(value, None)
        finally:
            db.close()

    def getall(self, infoid):
        db = self.opendb('c')
        try:
            return marshal.loads(db[infoid])
        finally:
            db.close()

    def set(self, infoid, **newvalues):
        db = self.opendb('c')
        try:
            if db.has_key(infoid):
                values = marshal.loads(db[infoid])
            else:
                values = {}
            values.update(newvalues)
            db[infoid] = marshal.dumps(values)
        finally:
            db.close()

    def list(self):
        db = self.opendb('r')
        try:
            return db.keys()
        finally:
            db.close()

    def destroy(self, infoid):
        db = self.opendb('c')
        try:
            if db.has_key(infoid):
                del db[infoid]
        finally:
            db.close()

    def opendb(self, mode):
        '''Low-level database opener that gets around anydbm/dbm
           eccentricities.
        '''
        # figure the class db type
        path = os.path.join(os.getcwd(), self.dir, self.name)
        if self._db_type is None:
            self.cache_db_type(path)

        db_type = self._db_type

        # new database? let anydbm pick the best dbm
        if not db_type:
            return anydbm.open(path, 'c')

        # open the database with the correct module
        dbm = __import__(db_type)
        return dbm.open(path, mode)

    def commit(self):
        pass

class Sessions(BasicDatabase):
    name = 'sessions'

class OneTimeKeys(BasicDatabase):
    name = 'otks'

