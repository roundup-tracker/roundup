#$Id: sessions_rdbms.py,v 1.4 2006-04-27 04:03:11 richard Exp $
"""This module defines a very basic store that's used by the CGI interface
to store session and one-time-key information.

Yes, it's called "sessions" - because originally it only defined a session
class. It's now also used for One Time Key handling too.
"""
__docformat__ = 'restructuredtext'

import os, time

class BasicDatabase:
    ''' Provide a nice encapsulation of an RDBMS table.

        Keys are id strings, values are automatically marshalled data.
    '''
    def __init__(self, db):
        self.db = db
        self.cursor = self.db.cursor

    def clear(self):
        self.cursor.execute('delete from %ss'%self.name)

    def exists(self, infoid):
        n = self.name
        self.cursor.execute('select count(*) from %ss where %s_key=%s'%(n,
            n, self.db.arg), (infoid,))
        return int(self.cursor.fetchone()[0])

    _marker = []
    def get(self, infoid, value, default=_marker):
        n = self.name
        self.cursor.execute('select %s_value from %ss where %s_key=%s'%(n,
            n, n, self.db.arg), (infoid,))
        res = self.cursor.fetchone()
        if not res:
            if default != self._marker:
                return default
            raise KeyError, 'No such %s "%s"'%(self.name, infoid)
        values = eval(res[0])
        return values.get(value, None)

    def getall(self, infoid):
        n = self.name
        self.cursor.execute('select %s_value from %ss where %s_key=%s'%(n,
            n, n, self.db.arg), (infoid,))
        res = self.cursor.fetchone()
        if not res:
            raise KeyError, 'No such %s "%s"'%(self.name, infoid)
        return eval(res[0])

    def set(self, infoid, **newvalues):
        c = self.cursor
        n = self.name
        a = self.db.arg
        c.execute('select %s_value from %ss where %s_key=%s'%(n, n, n, a),
            (infoid,))
        res = c.fetchone()
        if res:
            values = eval(res[0])
        else:
            values = {}
        values.update(newvalues)

        if res:
            sql = 'update %ss set %s_value=%s where %s_key=%s'%(n, n,
                a, n, a)
            args = (repr(values), infoid)
        else:
            sql = 'insert into %ss (%s_key, %s_time, %s_value) '\
                'values (%s, %s, %s)'%(n, n, n, n, a, a, a)
            args = (infoid, time.time(), repr(values))
        c.execute(sql, args)

    def destroy(self, infoid):
        self.cursor.execute('delete from %ss where %s_key=%s'%(self.name,
            self.name, self.db.arg), (infoid,))

    def updateTimestamp(self, infoid):
        ''' don't update every hit - once a minute should be OK '''
        now = time.time()
        self.cursor.execute('''update %ss set %s_time=%s where %s_key=%s
            and %s_time < %s'''%(self.name, self.name, self.db.arg,
            self.name, self.db.arg, self.name, self.db.arg),
            (now, infoid, now-60))

    def clean(self, now):
        """Age sessions, remove when they haven't been used for a week.
        """
        old = now - 60*60*24*7
        self.cursor.execute('delete from %ss where %s_time < %s'%(self.name,
            self.name, self.db.arg), (old, ))

class Sessions(BasicDatabase):
    name = 'session'

class OneTimeKeys(BasicDatabase):
    name = 'otk'

