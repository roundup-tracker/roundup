import os, shutil, unittest

from db_test_base import config


class SessionTest(object):
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = self.module.Database(config, 'admin')
        self.sessions = self.sessions_module.Sessions(self.db)
        self.otks = self.sessions_module.OneTimeKeys(self.db)

    def tearDown(self):
        del self.otks
        del self.sessions
        if hasattr(self, 'db'):
            self.db.close()
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)

    def testList(self):
        self.sessions.list()
        self.sessions.set('random_key', text='hello, world!')
        self.sessions.list()

    def testGetAll(self):
        self.sessions.set('random_key', text='hello, world!')
        self.assertEqual(self.sessions.getall('random_key'),
            {'text': 'hello, world!'})

    def testDestroy(self):
        self.sessions.set('random_key', text='hello, world!')
        self.assertEquals(self.sessions.getall('random_key'),
            {'text': 'hello, world!'})
        self.sessions.destroy('random_key')
        self.assertRaises(KeyError, self.sessions.getall, 'random_key')

    def testSetSession(self):
        self.sessions.set('random_key', text='hello, world!')
        self.assertEqual(self.sessions.get('random_key', 'text'),
            'hello, world!')

    def testUpdateSession(self):
        self.sessions.set('random_key', text='hello, world!')
        self.assertEqual(self.sessions.get('random_key', 'text'),
            'hello, world!')
        self.sessions.set('random_key', text='nope')
        self.assertEqual(self.sessions.get('random_key', 'text'), 'nope')

class DBMTest(SessionTest):
    import roundup.backends.sessions_dbm as sessions_module

class RDBMSTest(SessionTest):
    import roundup.backends.sessions_rdbms as sessions_module

