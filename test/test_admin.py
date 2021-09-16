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

#from roundup import instance

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

def normalize_file(filename, skiplines = [ None ]):
# https://stackoverflow.com/questions/4710067/using-python-for-deleting-a-specific-line-in-a-file

    with open(filename, "r+") as f:
        d = f.readlines()
        f.seek(0)
        for i in d:
            for skip in skiplines:
                if skip not in i:
                    f.write(i)
        f.truncate()

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
        admin.force = True  # force it to nuke existing tracker

        # Run under context manager to suppress output of help text.
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'install',
                      type, self.backend, settings ]
            ret = admin.main()
        self.assertEqual(ret, 0)

        # nuke any existing database (mysql/postgreql)
        # possible method in case admin.force doesn't work
        #tracker = instance.open(self.dirname)
        #if tracker.exists():
        #    tracker.nuke()

        # initialize tracker with initial_data.py. Put password
        # on cli so I don't have to respond to prompting.
        sys.argv=['main', '-i', self.dirname, 'initialise', 'admin']
        admin.force = True  # force it to nuke existing database
        ret = admin.main()
        self.assertEqual(ret, 0)


    def testGet(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.install_init()
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="foo bar"', 'assignedto=admin' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '1')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="bar foo bar"', 'assignedto=anonymous',
                      'superseder=1']
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '2')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'get', 'assignedto',
                      'issue2' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, '2')
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'get', 'superseder',
                      'issue2' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, "['1']")
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'get', 'title', 'issue1']
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, '"foo bar"')  ## why is capture inserting "??
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'get', 'tile', 'issue1']
            ret = self.admin.main()

        expected_err = 'Error: no such issue property "tile"'

        self.assertEqual(ret, 1)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out.index(expected_err), 0)
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'get', 'title', 'issue']
            ret = self.admin.main()

        expected_err = 'Error: "issue" not a node designator'

        self.assertEqual(ret, 1)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out.index(expected_err), 0)
        self.assertEqual(len(err), 0)

    def testInit(self):
        import sys
        self.admin=AdminTool()
        sys.argv=['main', '-i', self.dirname, 'install', 'classic', self.backend]
        ret = self.admin.main()
        print(ret)
        self.assertTrue(ret == 0)
        self.assertTrue(os.path.isfile(self.dirname + "/config.ini"))
        self.assertTrue(os.path.isfile(self.dirname + "/schema.py"))

    def testInitWithConfig_ini(self):
        import sys
        from roundup.configuration import CoreConfig
        self.admin=AdminTool()
        sys.argv=['main', '-i', self.dirname, 'install', 'classic', self.backend]
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
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="foo bar"', 'assignedto=admin' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '1')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="bar foo bar"', 'assignedto=anonymous' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '2')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'find', 'issue',
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
            sys.argv=['main', '-i', self.dirname, 'find', 'issue',
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
            sys.argv=['main', '-i', self.dirname, 'find', 'issue',
                      'assignedto=admin,anonymous']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        # out can be "['2', '1']" or "['1', '2']"
        # so eval to real list so Equal can do a list compare
        self.assertEqual(sorted(eval(out)), ['1', '2'])

    def testGenconfigUpdate(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys, filecmp

        self.admin=AdminTool()
        self.install_init()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'genconfig']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        expected = "Not enough arguments supplied"
        self.assertTrue(expected in out)

        # Reopen the db closed by previous call
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'genconfig',
                      self.dirname + "/config2.ini"]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        # FIXME get better successful test later.
        expected = ""
        self.assertTrue(expected in out)
        self.assertTrue(os.path.isfile(self.dirname + "/config2.ini"))
        # Files aren't the same. Lines need to be removed.
        # like user, web, backend etc. Genconfig generates a file
        # to be customized.
        #self.assertTrue(filecmp.cmp(self.dirname + "/config2.ini",
        #                            self.dirname + "/config.ini"))

        # Reopen the db closed by previous call
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'update',
                      self.dirname + "/foo2.ini"]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        # FIXME get better successful test later.
        expected = ""
        self.assertTrue(expected in out)
        self.assertTrue(os.path.isfile(self.dirname + "/foo2.ini"))

        # Autogenerated date header is different. Remove it
        # so filecmp passes.
        normalize_file(self.dirname + "/foo2.ini",
                       [ '# Autogenerated at' ])
        normalize_file(self.dirname + "/config.ini",
                       [ '# Autogenerated at' ])

        self.assertTrue(filecmp.cmp(self.dirname + "/config.ini",
                                    self.dirname + "/foo2.ini"))


    def testCliParse(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.admin=AdminTool()
        self.install_init()

        # test partial command lookup fin -> calls find

        with captured_output() as (out, err):
            ''' assignedto is not a valid property=value, so
                report error.
            '''
            sys.argv=['main', '-i', self.dirname, 'fin', 'issue',
                      'assignedto=1']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        expected="[ '1' ]"
        self.assertTrue(expected, out)

        # Reopen the db closed by previous call
        self.admin=AdminTool()
        # test multiple matches
        with captured_output() as (out, err):
            ''' assignedto is not a valid property=value, so
                report error.
            '''
            sys.argv=['main', '-i', self.dirname, 'f', 'issue',
                      'assignedto']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        expected='Multiple commands match "f": filter, find'
        self.assertEqual(expected, out)

        # Reopen the db closed by previous call
        self.admin=AdminTool()
        # test broken command lookup xyzzy is not a valid command
        with captured_output() as (out, err):
            ''' assignedto is not a valid property=value, so
                report error.
            '''
            sys.argv=['main', '-i', self.dirname, 'xyzzy', 'issue',
                      'assignedto']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        expected=('Unknown command "xyzzy" '
                  '("help commands" for a list)')
        self.assertEqual(expected, out)

        # Reopen the db closed by previous call
        self.admin=AdminTool()
        # test for keyword=value check
        with captured_output() as (out, err):
            ''' assignedto is not a valid property=value, so
                report error.
            '''
            sys.argv=['main', '-i', self.dirname, 'find', 'issue',
                      'assignedto']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        expected='Error: argument "assignedto" not propname=value'
        self.assertTrue(expected in out)

    def testFilter(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.admin=AdminTool()
        self.install_init()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="foo bar"', 'assignedto=admin' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '1')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="bar foo bar"', 'assignedto=anonymous' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '2')

        
        # Reopen the db closed by previous filter call
        # test string - one results, one value, substring
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'filter', 'user',
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
            sys.argv=['main', '-i', self.dirname, 'filter', 'user',
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
            sys.argv=['main', '-i', self.dirname, 'filter', 'user',
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
            sys.argv=['main', '-i', self.dirname, 'filter', 'user',
                      'username=admin,anonymous']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, "[]")

        # Reopen the db closed by previous filter call
        # test link using ids
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'filter', 'issue',
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
            sys.argv=['main', '-i', self.dirname, 'filter', 'issue',
                      'assignedto=admin,anonymous']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(sorted(eval(out)), ['1', '2'])

        # Reopen the db closed by previous filter call
        # 
        # case: transitive property valid match
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'filter', 'issue',
                      'assignedto.roles=Anonymous']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, "['2']")

        # Reopen the db closed by previous filter call
        #         self.admin=AdminTool()
        # case: transitive propery invalid prop
        self.admin=AdminTool()
        with captured_output() as (out, err):
            ''' assignedto is not a valid property=value, so
                report error.
            '''
            sys.argv=['main', '-i', self.dirname, 'filter', 'issue',
                      'assignedto.badprop=Admin']
            ret = self.admin.main()

        out = out.getvalue().strip()
        expected='Error: Class user has no property badprop in assignedto.badprop.'
        print(out[0:len(expected)])
        self.assertEqual(expected, out[0:len(expected)])

        # Reopen the db closed by previous filter call
        # 
        # case: transitive property invalid match
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname,
                      'filter', 'issue',
                      'assignedto.username=NoNAme']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print("me: " + out)
        print(err.getvalue().strip())
        self.assertEqual(out, "[]")

        # Reopen the db closed by previous filter call
        # 
        # case: transitive property invalid match
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-c',
                      'filter', 'issue',
                      'assignedto.username=NoNAme']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print("me: " + out)
        print(err.getvalue().strip())
        self.assertEqual(out, "")

        # Reopen the db closed by previous filter call
        # 
        # case: transitive property invalid match
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-c',
                      'filter', 'issue',
                      'assignedto.username=A']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print("me: " + out)
        print(err.getvalue().strip())
        self.assertEqual(out, "1,2")

        # Reopen the db closed by previous filter call
        # 
        # case: transitive property invalid match
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-s',
                      'filter', 'issue',
                      'assignedto.username=A']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print("me: " + out)
        print(err.getvalue().strip())
        self.assertEqual(out, "1 2")

        # Reopen the db closed by previous filter call
        # 
        # case: transitive property invalid match
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-S', ':',
                      '-d', 'filter', 'issue',
                      'assignedto.username=A']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print("me: " + out)
        print(err.getvalue().strip())
        self.assertEqual(out, "issue1:issue2")


    def disabletestHelpInitopts(self):

        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.install_init()
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'help', 'initopts']
            ret = self.admin.main()

        out = out.getvalue().strip()
        expected = [
        'Templates: minimal, jinja2, classic, responsive, devel',
        'Back ends: anydbm, sqlite'
        ]
        print(out)
        self.assertTrue(expected[0] in out)
        self.assertTrue("Back ends:" in out)

    def testSecurity(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.install_init()
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'security' ]
            ret = self.admin.main()

        result = """New Web users get the Role "User"
New Email users get the Role "User"
Role "admin":
 User may create everything (Create)
 User may edit everything (Edit)
 User may restore everything (Restore)
 User may retire everything (Retire)
 User may view everything (View)
 User may access the web interface (Web Access)
 User may access the rest interface (Rest Access)
 User may access the xmlrpc interface (Xmlrpc Access)
 User may manipulate user Roles through the web (Web Roles)
 User may use the email interface (Email Access)
Role "anonymous":
 User may access the web interface (Web Access)
 User is allowed to register new user (Register for "user" only)
 User is allowed to access issue (View for "issue" only)
 User is allowed to access file (View for "file" only)
 User is allowed to access msg (View for "msg" only)
 User is allowed to access keyword (View for "keyword" only)
 User is allowed to access priority (View for "priority" only)
 User is allowed to access status (View for "status" only)
  (Search for "user" only)
Role "user":
 User may access the web interface (Web Access)
 User may use the email interface (Email Access)
 User may access the rest interface (Rest Access)
 User may access the xmlrpc interface (Xmlrpc Access)
 User is allowed to access issue (View for "issue" only)
 User is allowed to edit issue (Edit for "issue" only)
 User is allowed to create issue (Create for "issue" only)
 User is allowed to access file (View for "file" only)
 User is allowed to edit file (Edit for "file" only)
 User is allowed to create file (Create for "file" only)
 User is allowed to access msg (View for "msg" only)
 User is allowed to edit msg (Edit for "msg" only)
 User is allowed to create msg (Create for "msg" only)
 User is allowed to access keyword (View for "keyword" only)
 User is allowed to edit keyword (Edit for "keyword" only)
 User is allowed to create keyword (Create for "keyword" only)
 User is allowed to access priority (View for "priority" only)
 User is allowed to access status (View for "status" only)
  (View for "user": ('id', 'organisation', 'phone', 'realname', 'timezone', 'username') only)
 User is allowed to view their own user details (View for "user" only)
 User is allowed to edit their own user details (Edit for "user": ('username', 'password', 'address', 'realname', 'phone', 'organisation', 'alternate_addresses', 'queries', 'timezone') only)
 User is allowed to view their own and public queries (View for "query" only)
  (Search for "query" only)
 User is allowed to edit their queries (Edit for "query" only)
 User is allowed to retire their queries (Retire for "query" only)
 User is allowed to restore their queries (Restore for "query" only)
 User is allowed to create queries (Create for "query" only)
"""
        print(out.getvalue())

        self.assertEqual(result, out.getvalue())
        self.assertEqual(ret, 0)

    def testSecurityInvalidAttribute(self):
        ''' Test with an invalid attribute.
            Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.maxDiff = None # we want full diff

        self.install_init()

        # edit in an invalid attribute/property
        with open(self.dirname + "/schema.py", "r+") as f:
            d = f.readlines()
            f.seek(0)
            for i in d:
                if "organisation" in i:
                    i = i.replace("'id', 'organisation'","'id', 'organization'")
                f.write(i)
            f.truncate()

        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'security' ]
            ret = self.admin.main()

        result = """New Web users get the Role "User"
New Email users get the Role "User"
Role "admin":
 User may create everything (Create)
 User may edit everything (Edit)
 User may restore everything (Restore)
 User may retire everything (Retire)
 User may view everything (View)
 User may access the web interface (Web Access)
 User may access the rest interface (Rest Access)
 User may access the xmlrpc interface (Xmlrpc Access)
 User may manipulate user Roles through the web (Web Roles)
 User may use the email interface (Email Access)
Role "anonymous":
 User may access the web interface (Web Access)
 User is allowed to register new user (Register for "user" only)
 User is allowed to access issue (View for "issue" only)
 User is allowed to access file (View for "file" only)
 User is allowed to access msg (View for "msg" only)
 User is allowed to access keyword (View for "keyword" only)
 User is allowed to access priority (View for "priority" only)
 User is allowed to access status (View for "status" only)
  (Search for "user" only)
Role "user":
 User may access the web interface (Web Access)
 User may use the email interface (Email Access)
 User may access the rest interface (Rest Access)
 User may access the xmlrpc interface (Xmlrpc Access)
 User is allowed to access issue (View for "issue" only)
 User is allowed to edit issue (Edit for "issue" only)
 User is allowed to create issue (Create for "issue" only)
 User is allowed to access file (View for "file" only)
 User is allowed to edit file (Edit for "file" only)
 User is allowed to create file (Create for "file" only)
 User is allowed to access msg (View for "msg" only)
 User is allowed to edit msg (Edit for "msg" only)
 User is allowed to create msg (Create for "msg" only)
 User is allowed to access keyword (View for "keyword" only)
 User is allowed to edit keyword (Edit for "keyword" only)
 User is allowed to create keyword (Create for "keyword" only)
 User is allowed to access priority (View for "priority" only)
 User is allowed to access status (View for "status" only)
  (View for "user": ('id', 'organization', 'phone', 'realname', 'timezone', 'username') only)

  **Invalid properties for user: ['organization']

"""
        print(out.getvalue())

        self.assertEqual(result, out.getvalue())
        self.assertEqual(ret, 1)

    def testSet(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.install_init()
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="foo bar"', 'assignedto=admin' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '1')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="bar foo bar"', 'assignedto=anonymous' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '2')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'set', 'issue2', 'title="new title"']
            ret = self.admin.main()

        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, '')
        self.assertEqual(err, '')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'set', 'issue2',
                      'tile="new title"']
            ret = self.admin.main()

        expected_err = "Error: 'tile' is not a property of issue"

        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out.index(expected_err), 0)
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'set', 'issue2']
            ret = self.admin.main()

        expected_err = "Error: Not enough arguments supplied"

        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out.index(expected_err), 0)
        self.assertEqual(len(err), 0)


        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'set',
                      'issue2,issue1,issue', "status=1" ]
            ret = self.admin.main()

        expected_err = 'Error: "issue" not a node designator'

        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out.index(expected_err), 0)
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'set',
                      'issue2,issue1,user2', "status=1" ]
            ret = self.admin.main()

        expected_err = "Error: 'status' is not a property of user"

        out = out.getvalue().strip()
        err = err.getvalue().strip()
        print(out)
        print(expected_err)
        print(err)
        self.assertEqual(out.index(expected_err), 0)
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'set',
                      'issue2,issue1,issue1000', "status=1" ]
            ret = self.admin.main()

        expected_err = 'Error: no such issue 1000'

        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out.index(expected_err), 0)
        self.assertEqual(len(err), 0)

    def testSetOnClass(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.install_init()

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="foo bar"', 'assignedto=admin' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '1')

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="bar foo bar"', 'assignedto=anonymous' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '2')

        # Run this test in a separate test.
        # It can cause a database timeout/resource
        # unavailable error for anydbm when run with other tests.
        # Not sure why.
        # Set assignedto=2 for all issues
        ## verify that issue 1 and 2 are assigned to user1 and user2
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'table', 'issue',
            'assignedto']
            ret = self.admin.main()

        expected = "Assignedto\n1         \n2"
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, expected)
        self.assertEqual(len(err), 0)
        self.admin=AdminTool()
        # do the set
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'set', 'issue',
            'assignedto=2']
            ret = self.admin.main()

        expected_err = ""

        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, '')
        self.assertEqual(err, '')

        ## verify that issue 1 and 2 are assigned to user2 and user2
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'table', 'issue',
            'assignedto']
            ret = self.admin.main()

        expected = "Assignedto\n2         \n2"
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, expected)
        self.assertEqual(len(err), 0)

    def testSpecification(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.install_init()
        self.admin=AdminTool()

        spec= [ 'username: <roundup.hyperdb.String> (key property)',
                'alternate_addresses: <roundup.hyperdb.String>',
                'realname: <roundup.hyperdb.String>',
                'roles: <roundup.hyperdb.String>',
                'organisation: <roundup.hyperdb.String>',
                'queries: <roundup.hyperdb.Multilink to "query">',
                'phone: <roundup.hyperdb.String>',
                'address: <roundup.hyperdb.String>',
                'timezone: <roundup.hyperdb.String>',
                'password: <roundup.hyperdb.Password>',
            ]
            
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'specification', 'user']
            ret = self.admin.main()

        outlist = out.getvalue().strip().split("\n")
        print(outlist)
        self.assertEqual(sorted(outlist), sorted(spec))

    def testRetireRestore(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        # create user1 at id 3
        self.install_init()
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'user',
                      'username=user1', 'address=user1' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '3')

        # retire user1 at id 3
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'retire', 'user3']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '')

        # create new user1 at id 4 - note need unique address to succeed.
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'create', 'user',
                      'username=user1', 'address=user1a' ]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '4')

        # fail to restore old user1 at id 3
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'restore', 'user3']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(out)
        self.assertIn('Error: Key property (username) of retired node clashes with existing one (user1)', out)

        # verify that user4 is listed
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'list', 'user']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(out)
        expected="1: admin\n   2: anonymous\n   4: user1"
        self.assertEqual(out, expected)

        # retire user4
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'retire', 'user4']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '')

        # now we can restore user3
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'restore', 'user3']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '')

        # verify that user3 is listed
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'list', 'user']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(out)
        expected="1: admin\n   2: anonymous\n   3: user1"
        self.assertEqual(out, expected)



    def testTable(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import sys

        self.install_init()
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'table' ]
            ret = self.admin.main()

        expected = 'Error: Not enough arguments supplied'

        out = out.getvalue().strip()
        print(out)
        print(expected)
        self.assertTrue(expected in out)
        ####

        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'table', 
                      'id,realname,username' ]
            ret = self.admin.main()

        expected = 'Error: no such class "id,realname,username"'

        out = out.getvalue().strip()
        print(out)
        print(expected)
        self.assertTrue(expected in out)

        ####
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'table', 'user',
                      'id,realname,username:4:3' ]
            ret = self.admin.main()
        expected = 'Error: "username:4:3" not name:width'

        out = out.getvalue().strip()
        print(out)
        print(expected)
        self.assertTrue(expected in out)
 
        ####
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'table', 'user',
                      'id,realname,title:4' ]
            ret = self.admin.main()
        expected = 'Error: user has no property "title"'

        out = out.getvalue().strip()
        print(out)
        print(expected)
        self.assertTrue(expected in out)
 
        ####
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'table', 'user',
                      'id,realname,username:' ]
            ret = self.admin.main()

        # note whitespace matters. trailing spaces on lines 1 and 2
        expected = """Id Realname Username
1  None     admin   
2  None     anonymou"""

        out = out.getvalue().strip()
        print(out)
        print(expected)
        self.assertEqual(out, expected)

        ####
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'table', 'user',
                      'id,realname,username' ]
            ret = self.admin.main()

        # note whitespace matters. trailing spaces on lines 1 and 2
        expected = """Id Realname Username 
1  None     admin    
2  None     anonymous"""

        out = out.getvalue().strip()
        print(out)
        print(expected)
        self.assertEqual(out, expected)

        ####
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'table', 'user',
                      'id:4,realname:2,username:3' ]
            ret = self.admin.main()

        # note whitespace matters. trailing spaces on lines 1 and 2
        expected = """Id   Realname Username
1    No adm
2    No ano"""

        out = out.getvalue().strip()
        print(out)
        print(expected)
        self.assertEqual(out, expected)


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
