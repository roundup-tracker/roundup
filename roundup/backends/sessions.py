#$Id: sessions.py,v 1.2 2002-09-09 02:58:35 richard Exp $
'''
This module defines a very basic store that's used by the CGI interface
to store session information.
'''

import anydbm, whichdb, os, marshal

class Sessions:
    ''' Back onto an anydbm store.

        Keys are session id strings, values are marshalled data.
    '''
    def __init__(self, config):
        self.config = config
        self.dir = config.DATABASE
        # ensure files are group readable and writable
        os.umask(0002)

    def clear(self):
        path = os.path.join(self.dir, 'sessions')
        if os.path.exists(path):
            os.remove(path)
        elif os.path.exists(path+'.db'):    # dbm appends .db
            os.remove(path+'.db')

    def determine_db_type(self, path):
        ''' determine which DB wrote the class file
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
        return db_type

    def get(self, sessionid, value):
        db = self.opendb('c')
        try:
            if db.has_key(sessionid):
                values = marshal.loads(db[sessionid])
            else:
                return None
            return values.get(value, None)
        finally:
            db.close()

    def set(self, sessionid, **newvalues):
        db = self.opendb('c')
        try:
            if db.has_key(sessionid):
                values = marshal.loads(db[sessionid])
            else:
                values = {}
            values.update(newvalues)
            db[sessionid] = marshal.dumps(values)
        finally:
            db.close()

    def list(self):
        db = self.opendb('r')
        try:
            return db.keys()
        finally:
            db.close()

    def destroy(self, sessionid):
        db = self.opendb('c')
        try:
            if db.has_key(sessionid):
                del db[sessionid]
        finally:
            db.close()

    def opendb(self, mode):
        '''Low-level database opener that gets around anydbm/dbm
           eccentricities.
        '''
        # figure the class db type
        path = os.path.join(os.getcwd(), self.dir, 'sessions')
        db_type = self.determine_db_type(path)

        # new database? let anydbm pick the best dbm
        if not db_type:
            return anydbm.open(path, 'c')

        # open the database with the correct module
        dbm = __import__(db_type)
        return dbm.open(path, mode)

    def commit(self):
        pass

#
#$Log: not supported by cvs2svn $
#Revision 1.1  2002/07/30 08:22:38  richard
#Session storage in the hyperdb was horribly, horribly inefficient. We use
#a simple anydbm wrapper now - which could be overridden by the metakit
#backend or RDB backend if necessary.
#Much, much better.
#
#
#
