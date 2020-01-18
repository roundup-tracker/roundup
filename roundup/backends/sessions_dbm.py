"""This module defines a very basic store that's used by the CGI interface
to store session and one-time-key information.

Yes, it's called "sessions" - because originally it only defined a session
class. It's now also used for One Time Key handling too.
"""
__docformat__ = 'restructuredtext'

import os, marshal, time

from roundup.anypy.html import html_escape as escape

from roundup import hyperdb
from roundup.i18n import _
from roundup.anypy.dbm_ import anydbm, whichdb


class BasicDatabase:
    ''' Provide a nice encapsulation of an anydbm store.

        Keys are id strings, values are automatically marshalled data.
    '''
    _db_type = None
    name = None

    def __init__(self, db):
        self.config = db.config
        self.dir = db.config.DATABASE
        os.umask(db.config.UMASK)

    def exists(self, infoid):
        db = self.opendb('c')
        try:
            return infoid in db
        finally:
            db.close()

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
            db_type = whichdb(path)
            if not db_type:
                raise hyperdb.DatabaseError(
                    _("Couldn't identify database type"))
        elif os.path.exists(path+'.db'):
            # if the path ends in '.db', it's a dbm database, whether
            # anydbm says it's dbhash or not!
            db_type = 'dbm'
        self.__class__._db_type = db_type

    _marker = []

    def get(self, infoid, value, default=_marker):
        db = self.opendb('c')
        try:
            if infoid in db:
                values = marshal.loads(db[infoid])
            else:
                if default != self._marker:
                    return default
                raise KeyError('No such %s "%s"' % (self.name, escape(infoid)))
            return values.get(value, None)
        finally:
            db.close()

    def getall(self, infoid):
        db = self.opendb('c')
        try:
            try:
                d = marshal.loads(db[infoid])
                del d['__timestamp']
                return d
            except KeyError:
                raise KeyError('No such %s "%s"' % (self.name, escape(infoid)))
        finally:
            db.close()

    def set(self, infoid, **newvalues):
        db = self.opendb('c')
        try:
            if infoid in db:
                values = marshal.loads(db[infoid])
            else:
                values = {'__timestamp': time.time()}
            values.update(newvalues)
            db[infoid] = marshal.dumps(values)
        finally:
            db.close()

    def list(self):
        db = self.opendb('r')
        try:
            return list(db.keys())
        finally:
            db.close()

    def destroy(self, infoid):
        db = self.opendb('c')
        try:
            if infoid in db:
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

        retries_left = 15
        while True:
            try:
                handle = dbm.open(path, mode)
                break
            except OSError:
                # Primarily we want to catch and retry:
                #   [Errno 11] Resource temporarily unavailable retry
                # FIXME: make this more specific
                if retries_left < 0:
                    # We have used up the retries. Reraise the exception
                    # that got us here.
                    raise
                else:
                    # delay retry a bit
                    time.sleep(0.01)
                    retries_left = retries_left - 1
                    continue  # the while loop
        return handle

    def commit(self):
        pass

    def close(self):
        pass

    def updateTimestamp(self, sessid):
        ''' don't update every hit - once a minute should be OK '''
        sess = self.get(sessid, '__timestamp', None)
        now = time.time()
        if sess is None or now > sess + 60:
            self.set(sessid, __timestamp=now)

    def clean(self):
        ''' Remove session records that haven't been used for a week. '''
        now = time.time()
        week = 60*60*24*7
        for sessid in self.list():
            sess = self.get(sessid, '__timestamp', None)
            if sess is None:
                self.updateTimestamp(sessid)
                continue
            interval = now - sess
            if interval > week:
                self.destroy(sessid)


class Sessions(BasicDatabase):
    name = 'sessions'


class OneTimeKeys(BasicDatabase):
    name = 'otks'

# vim: set sts ts=4 sw=4 et si :
