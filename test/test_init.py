# $Id: test_init.py,v 1.1 2001-08-05 07:07:58 richard Exp $

import unittest, os, shutil, errno, imp, sys

from roundup.init import init

class MyTestCase(unittest.TestCase):
    def tearDown(self):
        try:
            shutil.rmtree('_test_dir')
        except OSError, error:
            if error.errno == errno.ENOENT: raise

class ClassicTestCase(MyTestCase):
    backend = 'anydbm'
    def testCreation(self):
        ae = self.assertEqual

        # create the instance
        init('_test_dir', 'classic', self.backend, 'sekrit')

        # check we can load the package
        instance = imp.load_package('_test_dir', '_test_dir')

        # and open the database
        db = instance.open()

        # check the basics of the schema and initial data set
        l = db.priority.list()
        ae(l, ['1', '2', '3', '4', '5'])
        l = db.status.list()
        ae(l, ['1', '2', '3', '4', '5', '6', '7', '8'])
        l = db.keyword.list()
        ae(l, [])
        l = db.user.list()
        ae(l, ['1'])
        l = db.msg.list()
        ae(l, [])
        l = db.file.list()
        ae(l, [])
        l = db.issue.list()
        ae(l, [])

class ExtendedTestCase(MyTestCase):
    backend = 'anydbm'
    def testCreation(self):
        ae = self.assertEqual

        # create the instance
        init('_test_dir', 'extended', self.backend, 'sekrit')

        # check we can load the package
        del sys.modules['_test_dir']
        instance = imp.load_package('_test_dir', '_test_dir')

        # and open the database
        db = instance.open()

        # check the basics of the schema and initial data set
        l = db.priority.list()
        ae(l, ['1', '2', '3', '4', '5'])
        l = db.status.list()
        ae(l, ['1', '2', '3', '4', '5', '6', '7', '8'])
        l = db.keyword.list()
        ae(l, [])
        l = db.user.list()
        ae(l, ['1'])
        l = db.msg.list()
        ae(l, [])
        l = db.file.list()
        ae(l, [])
        l = db.issue.list()
        ae(l, [])
        l = db.support.list()
        ae(l, [])
        l = db.rate.list()
        ae(l, ['1', '2', '3'])
        l = db.source.list()
        ae(l, ['1', '2', '3', '4'])
        l = db.platform.list()
        ae(l, ['1', '2', '3'])
        l = db.timelog.list()
        ae(l, [])

def suite():
    l = [unittest.makeSuite(ClassicTestCase, 'test'),
         unittest.makeSuite(ExtendedTestCase, 'test')]
    try:
        import bsddb
        x = ClassicTestCase
        x.backend = 'bsddb'
        l.append(unittest.makeSuite(x, 'test'))
        x = ExtendedTestCase
        x.backend = 'bsddb'
        l.append(unittest.makeSuite(x, 'test'))
    except:
        print 'bsddb module not found, skipping bsddb DBTestCase'

    try:
        import bsddb3
        x = ClassicTestCase
        x.backend = 'bsddb3'
        l.append(unittest.makeSuite(x, 'test'))
        x = ExtendedTestCase
        x.backend = 'bsddb3'
        l.append(unittest.makeSuite(x, 'test'))
    except:
        print 'bsddb3 module not found, skipping bsddb3 DBTestCase'

    return unittest.TestSuite(l)

#
# $Log: not supported by cvs2svn $
#
#
# vim: set filetype=python ts=4 sw=4 et si
