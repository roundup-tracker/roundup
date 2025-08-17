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

import unittest, os, shutil, time
from roundup.anypy import strings

import pytest

try:
    from roundup.backends.sessions_redis import Sessions, OneTimeKeys
    skip_redis = lambda func, *args, **kwargs: func

    from redis import AuthenticationError, ConnectionError
except ImportError as e:
    from .pytest_patcher import mark_class
    skip_redis = mark_class(pytest.mark.skip(
        reason='Skipping redis tests: redis module not available'))

from .test_sqlite import sqliteOpener
from .test_anydbm import anydbmOpener

from .session_common import SessionTest

class RedisSessionTest(SessionTest):
    def setUp(self):
        '''This must not be called if redis can not be loaded. It will
           cause an error since the ConnectionError and
           AuthenticationError exceptions aren't defined.
        '''
        
        SessionTest.setUp(self)

        import os
        if 'pytest_redis_pw' in os.environ and os.environ['pytest_redis_pw']:
            pw = os.environ['pytest_redis_pw']
            if ':' in pw:
                # pw is user:password
                pw = "%s@" % pw
            else:
                # pw is just password
                pw = ":%s@" % pw
        else:
            pw = ""

        # redefine the session db's as redis.
        # close the existing session databases before opening new ones.
        self.db.Session.close()
        self.db.Otk.close()

        self.db.config.SESSIONDB_BACKEND = "redis"
        self.db.config.SESSIONDB_REDIS_URL = \
                    'redis://%slocalhost:6379/15?health_check_interval=2' % pw
        self.db.Session = None
        self.db.Otk = None
        self.sessions = self.db.getSessionManager()
        self.otks = self.db.getOTKManager()

        try:
            self.sessions.redis.keys()
        except (AuthenticationError, ConnectionError) as e:
            self.skipTest('Redis server unavailable: "%s".' % e)

        # database should be empty. Verify so we don't clobber
        # somebody's working database.
        self.assertEqual(self.sessions.redis.keys(), [],
            "Tests will not run on a db with keys. "
            "Run flushdb in 'redis-cli -n 15 -p 6379 -h localhost' "
            "to empty db first")
        self.assertEqual(self.otks.redis.keys(), [],
            "Tests will not run on a db with keys. "
            "Run flushdb in 'redis-cli -n 15 -p 6379 -h localhost' "
            "to empty db first")

    def tearDown(self):
        self.sessions.clear()
        self.otks.clear()

        SessionTest.tearDown(self)

        # reset to default session backend
        self.db.config.SESSIONDB_BACKEND = ""
        self.db.Session = None
        self.db.Otk = None
        self.sessions = None
        self.otks = None


    def get_ts(self, key="random_session"):
        db_tstamp = self.db.Session.redis.ttl(
            self.db.Session.makekey(key)) + \
            time.time()
        print(db_tstamp)
        return (db_tstamp,)

@skip_redis
class redis_sqliteSessionTest(sqliteOpener, RedisSessionTest, unittest.TestCase):
    s2b = lambda x,y : y

    def testLifetime(self):
        ts = self.sessions.lifetime(300)
        print(ts)
        now = time.time()
        print(now)
        self.assertGreater(now + 302, ts)
        self.assertLess(now + 298, ts)

    def testDbType(self):
        self.assertIn("roundlite", repr(self.db))
        self.assertIn("roundup.backends.sessions_redis.Sessions", repr(self.db.Session))

@skip_redis
class redis_anydbmSessionTest(anydbmOpener, RedisSessionTest, unittest.TestCase):
    s2b = lambda x,y: strings.s2b(y)

    def testLifetime(self):
        ts = self.sessions.lifetime(300)
        print(ts)
        now = time.time()
        print(now)
        self.assertGreater(now + 302, ts)
        self.assertLess(now + 298, ts)

    def testDbType(self):
        self.assertIn("back_anydbm", repr(self.db))
        self.assertIn("roundup.backends.sessions_redis.Sessions", repr(self.db.Session))
