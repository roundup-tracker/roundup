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

import unittest, os, shutil

from roundup import configuration
from roundup.backends import back_anydbm
from roundup.hyperdb import String, Password, Link, Multilink, Date, \
    Interval

config = configuration.CoreConfig()
config.DATABASE = "_test_dir"

class SchemaTestCase(unittest.TestCase):
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = back_anydbm.Database(config, 'admin')
        self.db.post_init()
        self.db.clear()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(config.DATABASE)

    def testA_Status(self):
        status = back_anydbm.Class(self.db, "status", name=String())
        self.assert_(status, 'no class object generated')
        status.setkey("name")
        val = status.create(name="unread")
        self.assertEqual(val, '1', 'expecting "1"')
        val = status.create(name="in-progress")
        self.assertEqual(val, '2', 'expecting "2"')
        val = status.create(name="testing")
        self.assertEqual(val, '3', 'expecting "3"')
        val = status.create(name="resolved")
        self.assertEqual(val, '4', 'expecting "4"')
        val = status.count()
        self.assertEqual(val, 4, 'expecting 4')
        val = status.list()
        self.assertEqual(val, ['1', '2', '3', '4'], 'blah')
        val = status.lookup("in-progress")
        self.assertEqual(val, '2', 'expecting "2"')
        status.retire('3')
        val = status.list()
        self.assertEqual(val, ['1', '2', '4'], 'blah')

    def testB_Issue(self):
        issue = back_anydbm.Class(self.db, "issue", title=String(),
            status=Link("status"))
        self.assert_(issue, 'no class object returned')

    def testC_User(self):
        user = back_anydbm.Class(self.db, "user", username=String(),
            password=Password())
        self.assert_(user, 'no class object returned')
        user.setkey("username")

# vim: set filetype=python sts=4 sw=4 et si :
