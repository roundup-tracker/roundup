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
# $Id: test_metakit.py,v 1.7 2004-11-18 16:33:43 a1s Exp $
import unittest, os, shutil, time, weakref

from db_test_base import DBTest, ROTest, SchemaTest, ClassicInitTest, config, password

from roundup.backends import get_backend, have_backend

class metakitOpener:
    if have_backend('metakit'):
        module = get_backend('metakit')
        module._instances = weakref.WeakValueDictionary()

    def nuke_database(self):
        shutil.rmtree(config.DATABASE)

class metakitDBTest(metakitOpener, DBTest):
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

    def testPasswordUnset(self):
        # XXX: metakit can't unset Numbers (id's) :(
        x = password.Password('x')
        nid = self.db.user.create(username='foo', password=x)
        self.db.user.set(nid, assignable=None)
        self.assertEqual(self.db.user.get(nid, "assignable"), 0)

class metakitROTest(metakitOpener, ROTest):
    pass

class metakitSchemaTest(metakitOpener, SchemaTest):
    pass

class metakitClassicInitTest(ClassicInitTest):
    backend = 'metakit'

from session_common import DBMTest
class metakitSessionTest(metakitOpener, DBMTest):
    pass

def test_suite():
    suite = unittest.TestSuite()
    if not have_backend('metakit'):
        print 'Skipping metakit tests'
        return suite
    print 'Including metakit tests'
    suite.addTest(unittest.makeSuite(metakitDBTest))
    suite.addTest(unittest.makeSuite(metakitROTest))
    suite.addTest(unittest.makeSuite(metakitSchemaTest))
    suite.addTest(unittest.makeSuite(metakitClassicInitTest))
    suite.addTest(unittest.makeSuite(metakitSessionTest))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: set et sts=4 sw=4 :
