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

# https://stackoverflow.com/questions/4219717/how-to-assert-output-with-nosetest-unittest-in-python
# lightly modified
from contextlib import contextmanager
_py3 = sys.version_info[0] > 2
if _py3:
    from io import StringIO # py3
else:
    from StringIO import StringIO # py2

@contextmanager
def captured_output():
    new_out, new_err = StringIO(), StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = new_out, new_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = old_out, old_err

class AdminTest(object):

    backend = None

    def setUp(self):
        self.dirname = '_test_admin'

    def tearDown(self):
        try:
            shutil.rmtree(self.dirname)
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def install_init(self, type="classic",
                     settings="mail_domain=example.com," +
                     "mail_host=localhost," +
                     "tracker_web=http://test/," +
                     "rdbms_name=rounduptest," +
                     "rdbms_user=rounduptest," +
                     "rdbms_password=rounduptest," +
                     "rdbms_template=template0"
    ):
        ''' install tracker with settings for required config.ini settings.
        '''

        admin=AdminTool()

        # Run under context manager to suppress output of help text.
        with captured_output() as (out, err):
            sys.argv=['main', '-i', '_test_admin', 'install',
                      type, self.backend, settings ]
            ret = admin.main()
        self.assertEqual(ret, 0)

        # initialize tracker with initial_data.py. Put password
        # on cli so I don't have to respond to prompting.
        sys.argv=['main', '-i', '_test_admin', 'initialise', 'admin']
        ret = admin.main()
        self.assertEqual(ret, 0)

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

    def testFind(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.admin=AdminTool()
        self.install_init()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', '_test_admin', 'create', 'issue',
                      'title="foo bar"', 'assignedto=admin' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '1')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', '_test_admin', 'create', 'issue',
                      'title="bar foo bar"', 'assignedto=anonymous' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '2')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', '_test_admin', 'find', 'issue',
                      'assignedto=1']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, "['1']")

        # Reopen the db closed by previous filter call
        self.admin=AdminTool()
        with captured_output() as (out, err):
            ''' 1,2 should return all entries that have assignedto
                either admin or anonymous
            '''
            sys.argv=['main', '-i', '_test_admin', 'find', 'issue',
                      'assignedto=1,2']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        # out can be "['2', '1']" or "['1', '2']"
        # so eval to real list so Equal can do a list compare
        self.assertEqual(sorted(eval(out)), ['1', '2'])

        # Reopen the db closed by previous filter call
        self.admin=AdminTool()
        with captured_output() as (out, err):
            ''' 1,2 should return all entries that have assignedto
                either admin or anonymous
            '''
            sys.argv=['main', '-i', '_test_admin', 'find', 'issue',
                      'assignedto=admin,anonymous']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        # out can be "['2', '1']" or "['1', '2']"
        # so eval to real list so Equal can do a list compare
        self.assertEqual(sorted(eval(out)), ['1', '2'])

    def testFilter(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.admin=AdminTool()
        self.install_init()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', '_test_admin', 'create', 'issue',
                      'title="foo bar"', 'assignedto=admin' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '1')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', '_test_admin', 'create', 'issue',
                      'title="bar foo bar"', 'assignedto=anonymous' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '2')

        
        # Reopen the db closed by previous filter call
        # test string - one results, one value, substring
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', '_test_admin', 'filter', 'user',
                      'username=admin']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, "['1']")

        # Reopen the db closed by previous filter call
        # test string - two results, two values, substring
        self.admin=AdminTool()
        with captured_output() as (out, err):
            ''' a,n should return all entries that have an a and n
                so admin or anonymous
            '''
            sys.argv=['main', '-i', '_test_admin', 'filter', 'user',
                      'username=a,n']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        # out can be "['2', '1']" or "['1', '2']"
        # so eval to real list so Equal can do a list compare
        self.assertEqual(sorted(eval(out)), ['1', '2'])

        # Reopen the db closed by previous filter call
        # test string - one result, two values, substring
        self.admin=AdminTool()
        with captured_output() as (out, err):
            ''' a,y should return all entries that have an a and y
                so anonymous
            '''
            sys.argv=['main', '-i', '_test_admin', 'filter', 'user',
                      'username=a,y']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, "['2']")

        # Reopen the db closed by previous filter call
        # test string - no results
        self.admin=AdminTool()
        with captured_output() as (out, err):
            ''' will return empty set as admin!=anonymous
            '''
            sys.argv=['main', '-i', '_test_admin', 'filter', 'user',
                      'username=admin,anonymous']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, "[]")

        # Reopen the db closed by previous filter call
        # test link using ids
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', '_test_admin', 'filter', 'issue',
                      'assignedto=1,2']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(sorted(eval(out)), ['1', '2'])

        # Reopen the db closed by previous filter call
        # test link using names
        self.admin=AdminTool()
        with captured_output() as (out, err):
            ''' will return empty set as admin!=anonymous
            '''
            sys.argv=['main', '-i', '_test_admin', 'filter', 'issue',
                      'assignedto=admin,anonymous']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(sorted(eval(out)), ['1', '2'])

    def testSpecification(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.install_init()
        self.admin=AdminTool()

        import inspect
        
        spec='''username: <roundup.hyperdb.String> (key property)
              alternate_addresses: <roundup.hyperdb.String>
              realname: <roundup.hyperdb.String>
              roles: <roundup.hyperdb.String>
              organisation: <roundup.hyperdb.String>
              queries: <roundup.hyperdb.Multilink to "query">
              phone: <roundup.hyperdb.String>
              address: <roundup.hyperdb.String>
              timezone: <roundup.hyperdb.String>
              password: <roundup.hyperdb.Password>'''

        spec = inspect.cleandoc(spec)
        with captured_output() as (out, err):
            sys.argv=['main', '-i', '_test_admin', 'specification', 'user']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, spec)


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
