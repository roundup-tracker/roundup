#
# Copyright (C) 2007 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

from __future__ import print_function
import unittest, os, shutil, errno, sys, difflib, cgi, re

from roundup.admin import AdminTool

from . import db_test_base
from .test_mysql import skip_mysql
from .test_postgresql import skip_postgresql


class AdminTest(object):

    backend = None

    def setUp(self):
        self.dirname = '_test_admin'

    def tearDown(self):
        try:
            shutil.rmtree(self.dirname)
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def testInit(self):
        import sys
        self.admin=AdminTool()
        sys.argv=['main', '-i', '_test_admin', 'install', 'classic', self.backend]
        ret = self.admin.main()
        print(ret)
        self.assertTrue(ret == 0)
        self.assertTrue(os.path.isfile(self.dirname + "/config.ini"))
        self.assertTrue(os.path.isfile(self.dirname + "/schema.py"))
        


class anydbmAdminTest(AdminTest, unittest.TestCase):
    backend = 'anydbm'


@skip_mysql
class mysqlAdminTest(AdminTest, unittest.TestCase):
    backend = 'mysql'


class sqliteAdminTest(AdminTest, unittest.TestCase):
    backend = 'sqlite'


@skip_postgresql
class postgresqlAdminTest(AdminTest, unittest.TestCase):
    backend = 'postgresql'
