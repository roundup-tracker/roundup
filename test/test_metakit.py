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
# 
# $Id: test_metakit.py,v 1.1 2003-10-25 22:53:26 richard Exp $ 

import unittest, os, shutil, time, weakref

from db_test_base import DBTest, ROTest, SchemaTest, \
    ClassicInitTest

from roundup import backends

class metakitOpener:
    if hasattr(backends, 'metakit'):
        from roundup.backends import metakit as module
        module._instances = weakref.WeakValueDictionary()

class metakitDBTest(metakitOpener, DBTest):
    def testTransactions(self):
        # remember the number of items we started
        num_issues = len(self.db.issue.list())
        self.db.issue.create(title="don't commit me!", status='1')
        self.assertNotEqual(num_issues, len(self.db.issue.list()))
        self.db.rollback()
        self.assertEqual(num_issues, len(self.db.issue.list()))
        self.db.issue.create(title="please commit me!", status='1')
        self.assertNotEqual(num_issues, len(self.db.issue.list()))
        self.db.commit()
        self.assertNotEqual(num_issues, len(self.db.issue.list()))
        self.db.rollback()
        self.assertNotEqual(num_issues, len(self.db.issue.list()))
        self.db.file.create(name="test", type="text/plain", content="hi")
        self.db.rollback()
        num_files = len(self.db.file.list())
        for i in range(10):
            self.db.file.create(name="test", type="text/plain", 
                    content="hi %d"%(i))
            self.db.commit()
        # TODO: would be good to be able to ensure the file is not on disk after
        # a rollback...
        num_files2 = len(self.db.file.list())
        self.assertNotEqual(num_files, num_files2)
        self.db.file.create(name="test", type="text/plain", content="hi")
        num_rfiles = len(os.listdir(self.db.config.DATABASE + '/files/file/0'))
        self.db.rollback()
        num_rfiles2 = len(os.listdir(self.db.config.DATABASE + '/files/file/0'))
        self.assertEqual(num_files2, len(self.db.file.list()))
        self.assertEqual(num_rfiles2, num_rfiles-1)

    def testBooleanUnset(self):
        # XXX: metakit can't unset Booleans :(
        nid = self.db.user.create(username='foo', assignable=1)
        self.db.user.set(nid, assignable=None)
        self.assertEqual(self.db.user.get(nid, "assignable"), 0)

    def testNumberUnset(self):
        # XXX: metakit can't unset Numbers :(
        nid = self.db.user.create(username='foo', age=1)
        self.db.user.set(nid, age=None)
        self.assertEqual(self.db.user.get(nid, "age"), 0)

class metakitROTest(metakitOpener, ROTest):
    pass

class metakitSchemaTest(metakitOpener, SchemaTest):
    pass

class metakitClassicInitTest(ClassicInitTest):
    backend = 'metakit'

def test_suite():
    suite = unittest.TestSuite()
    if not hasattr(backends, 'metakit'):
        print 'Skipping metakit tests'
        return suite
    print 'Including metakit tests'
    suite.addTest(unittest.makeSuite(metakitDBTest))
    suite.addTest(unittest.makeSuite(metakitROTest))
    suite.addTest(unittest.makeSuite(metakitSchemaTest))
    suite.addTest(unittest.makeSuite(metakitClassicInitTest))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

