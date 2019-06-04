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

    def testInitWithConfig_ini(self):
        import sys
        from roundup.configuration import CoreConfig
        self.admin=AdminTool()
        sys.argv=['main', '-i', '_test_admin', 'install', 'classic', self.backend]
        # create a config_ini.ini file in classic template
        templates=self.admin.listTemplates()
        config_ini_content = "[mail]\n# comment\ndebug = SendMail.LOG\n"
        config_ini_path = templates['classic']['path'] + '/config_ini.ini'
        config_ini_file = open(config_ini_path, "w")
        config_ini_file.write(config_ini_content)
        config_ini_file.close()

        try:
            ret = self.admin.main()
        finally:
            try:
                # ignore file not found
                os.remove(config_ini_path)
            except OSError as e:  # FileNotFound exception under py3
                if e.errno == 2:
                    pass
                else:
                    raise

        print(ret)
        self.assertTrue(ret == 0)
        self.assertTrue(os.path.isfile(self.dirname + "/config.ini"))
        self.assertTrue(os.path.isfile(self.dirname + "/schema.py"))
        config=CoreConfig(self.dirname)
        self.assertEqual(config['MAIL_DEBUG'], self.dirname + "/SendMail.LOG")
        


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
