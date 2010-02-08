# $Id: test_memorydb.py,v 1.4 2004-11-03 01:34:21 richard Exp $ 

import unittest, os, shutil, time

from roundup import hyperdb

from db_test_base import DBTest, ROTest, SchemaTest, config, setupSchema
import memorydb

class memorydbOpener:
    module = memorydb

    def nuke_database(self):
        # really kill it
        self.db = None

    db = None
    def open_database(self):
        if self.db is None:
            self.db = self.module.Database(config, 'admin')
        return self.db

    def setUp(self):
        self.open_database()
        setupSchema(self.db, 1, self.module)

    def tearDown(self):
        if self.db is not None:
            self.db.close()

    # nuke and re-create db for restore
    def nukeAndCreate(self):
        self.db.close()
        self.nuke_database()
        self.db = self.module.Database(config, 'admin')
        setupSchema(self.db, 0, self.module)

class memorydbDBTest(memorydbOpener, DBTest):
    pass

class memorydbROTest(memorydbOpener, ROTest):
    def setUp(self):
        self.db = self.module.Database(config)
        setupSchema(self.db, 0, self.module)

class memorydbSchemaTest(memorydbOpener, SchemaTest):
    pass

from session_common import DBMTest
class memorydbSessionTest(memorydbOpener, DBMTest):
    def setUp(self):
        self.db = self.module.Database(config, 'admin')
        setupSchema(self.db, 1, self.module)
        self.sessions = self.db.sessions

def test_suite():
    suite = unittest.TestSuite()
    print 'Including memorydb tests'
    suite.addTest(unittest.makeSuite(memorydbDBTest))
    suite.addTest(unittest.makeSuite(memorydbROTest))
    suite.addTest(unittest.makeSuite(memorydbSchemaTest))
    suite.addTest(unittest.makeSuite(memorydbSessionTest))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)


# vim: set filetype=python ts=4 sw=4 et si

