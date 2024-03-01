"""This module defines a redis based store that's used by
the CGI interface to store session and one-time-key
information.

Yes, it's called "sessions" - because originally it only
defined a session class. It's now also used for One Time Key
handling too.

It uses simple strings rather than redis hash structure
because the hash the values are always strings. We need to
be able to represent the same data types available to rdbms
and dbm session stores.

session_dbm uses marshal.dumps and marshal.loads. This seems
4 or 18 times faster than the repr()/eval() used by
session_rdbms. So use marshal even though it is impossible
to read when viewing (using redis-cli).
"""
__docformat__ = 'restructuredtext'

import marshal
import redis
import time

from roundup.anypy.html import html_escape as escape

from roundup.i18n import _

from roundup.backends.sessions_common import SessionCommon


class BasicDatabase(SessionCommon):
    ''' Provide a nice encapsulation of a redis store.

        Keys are id strings, values are automatically marshalled data.
    '''
    name = None
    default_lifetime = 60*60*24*7  # 1 week

    # FIXME: figure out how to allow admin to change this
    # to repr/eval using interfaces.py or other method.
    # marshalled data is not readable when debugging.
    tostr = marshal.dumps
    todict = marshal.loads

    def __init__(self, db):
        self.config = db.config
        url = self.config.SESSIONDB_REDIS_URL

        # Example at default port without auth.
        #    redis://localhost:6379/0?health_check_interval=2
        #
        # Do not allow decode_responses=True in url, data is
        # marshal'ed binary data that will get broken by decoding.
        # Enforce this in configuration.
        self.redis = redis.Redis.from_url(url=url, decode_responses=False)

    def makekey(self, key):
        '''method to namespace all keys using self.name:....'''
        return "%s:%s" % (self.name, key)

    def exists(self, infoid):
        return self.redis.exists(self.makekey(infoid))

    def clear(self):
        '''Delete all keys from the database.'''
        self.redis.flushdb()

    _marker = []

    def get(self, infoid, value, default=_marker):
        '''get a specific value from the data associated with a key'''
        infoid = self.makekey(infoid)
        v = self.redis.get(infoid)
        if not v:
            if default != self._marker:
                return default
            raise KeyError(_('Key %(key)s not found in %(name)s '
                             'database.') % {"name": self.name,
                                            "key": escape(infoid)})
        return self.todict(v)[value]

    def getall(self, infoid):
        '''return all values associated with a key'''
        try:
            d = self.redis.get(self.makekey(infoid))
            if d is not None:
                d = self.todict(d)
            else:
                d = {}
            del d['__timestamp']
            return d
        except KeyError:
            # It is possible for d to be malformed missing __timestamp.
            # If so, we get a misleading error, but anydbm does the
            # same so....
            raise KeyError(_('Key %(key)s not found in %(name)s '
                             'database.') % {"name": self.name,
                                            "key": escape(infoid)})

        ''' def set_no_tranaction(self, infoid, **newvalues):
        """ this is missing transaction and may be affected by
            a race condition on update. This will work for
            redis-like embedded databases that don't support
            watch/multi/exec
        """
        infoid = self.makekey(infoid)
        timestamp=None
        values = self.redis.get(infoid)
        if values is not None:
            values = self.todict(values)
        else:
            values={}
        try:
            timestamp = float(values['__timestamp'])
        except KeyError:
            pass  # stay at None

        if '__timestamp' in newvalues:
            try:
                float(newvalues['__timestamp'])
            except ValueError:
                # keep original timestamp if present
                newvalues['__timestamp'] = timestamp or \
                                        (time.time() + self.default_lifetime)
        else:
            newvalues['__timestamp'] = time.time() + self.default_lifetime

        values.update(newvalues)

        self.redis.set(infoid, self.tostr(values))
        self.redis.expireat(infoid, int(values['__timestamp']))
        '''

    def set(self, infoid, **newvalues):
        """ Implement set using watch/multi/exec to get some
            protection against a change committing between
            getting the data and setting new fields and
            saving.
        """
        infoid = self.makekey(infoid)
        timestamp = None

        with self.redis.pipeline() as transaction:
            # Give up and log after three tries.
            # Do not loop forever.
            for _retry in [1, 2, 3]:
                # I am ignoring transaction return values.
                # Assuming all errors will be via exceptions.
                # Not clear that return values that useful.
                transaction.watch(infoid)
                values = transaction.get(infoid)
                if values is not None:
                    values = self.todict(values)
                else:
                    values = {}

                try:
                    timestamp = float(values['__timestamp'])
                except KeyError:
                    pass  # stay at None

                if '__timestamp' in newvalues:
                    try:
                        float(newvalues['__timestamp'])
                    except ValueError:
                        # keep original timestamp if present
                        newvalues['__timestamp'] = timestamp or \
                                (time.time() + self.default_lifetime)
                else:
                    newvalues['__timestamp'] = time.time() + \
                                               self.default_lifetime

                values.update(newvalues)

                transaction.multi()
                transaction.set(infoid, self.tostr(values))
                transaction.expireat(infoid, int(values['__timestamp']))
                try:
                    # assume this works or raises an WatchError
                    # exception indicating I need to retry.
                    # Since this is not a real transaction, an error
                    # in one step doesn't roll back other changes.
                    # so I again ignore the return codes as it is not
                    # clear that I can do the rollback myself.
                    # Format and other errors (e.g. expireat('d', 'd'))
                    # raise exceptions that bubble up and result in mail
                    # to admin.
                    transaction.execute()
                    break
                except redis.exceptions.WatchError:
                    self.log_info(
                        _('Key %(key)s changed in %(name)s db') %
                          {"key": escape(infoid), "name": self.name}
                    )
            else:
                try:
                    username = values['user']
                except KeyError:
                    username = "Not Set"

                raise Exception(
                    _("Redis set failed after %(retries)d retries for "
                      "user %(user)s with key %(key)s") % {
                          "key": escape(infoid), "retries": _retry,
                          "user": username})

    def list(self):
        return list(self.redis.keys(self.makekey('*')))

    def destroy(self, infoid=None):
        '''use unlink rather than delete as unlink is async and doesn't
           wait for memory to be freed server-side
        '''
        self.redis.unlink(self.makekey(infoid))

    def commit(self):
        ''' no-op '''
        pass

    def lifetime(self, key_lifetime=None):
        """Return the proper timestamp to expire a key with key_lifetime
           specified in seconds. Default lifetime is self.default_lifetime.
        """
        return time.time() + (key_lifetime or self.default_lifetime)

    def updateTimestamp(self, sessid):
        ''' Even Redis can be overwhelmed by multiple updates, so
            only update if old session key is > 60 seconds old.
        '''
        sess = self.get(sessid, '__timestamp', None)
        now = time.time()
        # unlike other session backends, __timestamp is not set to now
        # but now + lifetime.
        if sess is None or now > sess + 60 - self.default_lifetime:
            lifetime = self.lifetime()
            # note set also updates the expireat on the key in redis
            self.set(sessid, __timestamp=lifetime)

    def clean(self):
        ''' redis handles key expiration, so nothing to do here.
        '''
        pass

    def close(self):
        ''' redis uses a connection pool that self manages, so nothing
            to do on close.'''
        pass


class Sessions(BasicDatabase):
    name = 'sessions'


class OneTimeKeys(BasicDatabase):
    name = 'otks'

# vim: set sts ts=4 sw=4 et si :
