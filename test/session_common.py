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

