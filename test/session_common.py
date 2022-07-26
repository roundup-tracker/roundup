import os, shutil, time, unittest

from .db_test_base import config

"""
here are three different impementations for these. I am trying to fix
them so they all act the same.

set with invalid timestamp:

   session_dbm/memorydb - sets to invalid timestamp if new or existing item.
   session_rdbms - sets to time.time if new item, keeps original
                   if item exists. (note that the timestamp is
                   a separate column, the timestamp embedded in the
                   value object in the db has the bad __timestamp.
   reconciled: set to time.time for new item, keeps original time
               of existing item.

Also updateTimestamp does not update the marshalled values idea of
   __timestamp. So get(item, '__timestamp') will not work as expected
   for rdbms backends, need a sql query to get the timestamp column.

FIXME need to add getTimestamp method to sessions_rdbms.py and
sessions_dbm.py.

"""
class SessionTest(object):
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = self.module.Database(config, 'admin')
        self.sessions = self.db.getSessionManager()
        self.otks = self.db.getOTKManager()

    def tearDown(self):
        if hasattr(self, 'db'):
            self.db.close()
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)

    def testList(self):
        '''Under dbm/memory sessions store, keys are returned as
           byte strings. self.s2b converts string to byte under those
           backends but is a no-op for rdbms based backends.

           Unknown why keys can be strings not bytes for get/set
           and work correctly.
        '''
        self.sessions.list()
        self.sessions.set('random_key', text='hello, world!')
        self.sessions.set('random_key2', text='hello, world!')
        self.assertEqual(self.sessions.list().sort(),
                [self.s2b('random_key'), self.s2b('random_key2')].sort())

    def testGetMissingKey(self):
        self.sessions.set('random_key', text='hello, world!', otherval='bar')
        with self.assertRaises(KeyError) as e:
            self.sessions.get('badc_key', 'text')

    def testGetAll(self):
        self.sessions.set('random_key', text='hello, world!', otherval='bar')
        self.assertEqual(self.sessions.getall('random_key'),
            {'text': 'hello, world!', 'otherval': 'bar'})

    def testDestroy(self):
        self.sessions.set('random_key', text='hello, world!')
        self.assertEqual(self.sessions.getall('random_key'),
            {'text': 'hello, world!'})
        self.sessions.destroy('random_key')
        self.assertRaises(KeyError, self.sessions.getall, 'random_key')

    def testClear(self):
        self.sessions.set('random_key', text='hello, world!')
        self.sessions.set('random_key2', text='hello, world!')
        self.sessions.set('random_key3', text='hello, world!')
        self.assertEqual(self.sessions.getall('random_key3'),
            {'text': 'hello, world!'})
        self.assertEqual(len(self.sessions.list()), 3)
        self.sessions.clear()
        self.assertEqual(len(self.sessions.list()), 0)

    def testSetSession(self):
        self.sessions.set('random_key', text='hello, world!', otherval='bar')
        self.assertEqual(self.sessions.get('random_key', 'text'),
            'hello, world!')
        self.assertEqual(self.sessions.get('random_key', 'otherval'),
            'bar')

    def testUpdateSession(self):
        self.sessions.set('random_key', text='hello, world!')
        self.assertEqual(self.sessions.get('random_key', 'text'),
            'hello, world!')
        self.sessions.set('random_key', text='nope')
        self.assertEqual(self.sessions.get('random_key', 'text'), 'nope')

    def testBadTimestamp(self):
        self.sessions.set('random_key',
                          text='hello, world!',
                          __timestamp='not a timestamp')
        ts = self.sessions.get('random_key', '__timestamp')
        self.assertNotEqual(ts, 'not a timestamp')
        # use {1,7} because db's don't pad the fraction to 7 digits.
        ts_re=r'^[0-9]{10,16}\.[0-9]{1,7}$'
        try:
            self.assertRegex(str(ts), ts_re)
        except AttributeError:   # 2.7 version
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore",category=DeprecationWarning)
                self.assertRegexpMatches(str(ts), ts_re)

        # now update with a bad timestamp, original timestamp should
        # be kept.
        self.sessions.set('random_key',
                          text='hello, world2!',
                          __timestamp='not a timestamp')
        item = self.sessions.get('random_key', "text")
        item_ts = self.sessions.get('random_key', "__timestamp")
        self.assertEqual(item, 'hello, world2!')
        self.assertAlmostEqual(ts, item_ts, 2)

    # overridden in dbm and memory backends
    def testUpdateTimestamp(self):
        def get_ts_via_sql(self):
            sql = '''select %(name)s_time from %(name)ss
                 where %(name)s_key = '%(session)s';'''% \
                     {'name': self.sessions.name,
                      'session': 'random_session'}

            self.sessions.cursor.execute(sql)
            db_tstamp = self.sessions.cursor.fetchone()
            return db_tstamp

        # make sure timestamp is older than one minute so update will apply
        timestamp = time.time() - 62
        self.sessions.set('random_session', text='hello, world!',
                          __timestamp=timestamp)

        self.sessions.updateTimestamp('random_session')
        # this doesn't work as the rdbms backends have a
        # session_time, otk_time column and the timestamp in the
        # session marshalled payload isn't updated. The dbm
        # backend does update the __timestamp value so it works
        # for dbm.
        #self.assertNotEqual (self.sessions.get('random_session',
        #                                       '__timestamp'),
        #                     timestamp)

        # use 61 to allow a fudge factor
        self.assertGreater(get_ts_via_sql(self)[0] - timestamp, 61)

    def testLifetime(self):
        ts = self.sessions.lifetime(300)
        week_ago =  time.time() - 60*60*24*7
        self.assertGreater(week_ago + 302, ts)
        self.assertLess(week_ago + 298, ts)
