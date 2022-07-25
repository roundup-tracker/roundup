import os, shutil, time, unittest

from .db_test_base import config


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
