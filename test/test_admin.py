#
# Copyright (C) 2007 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

from __future__ import print_function
import fileinput
import unittest, os, shutil, errno, sys, difflib, re

from roundup.admin import AdminTool

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

def replace_in_file(filename, original, replacement):
    """replace text in a file. All occurances of original
       will be replaced by replacement"""

    for line in fileinput.input(filename, inplace = 1): 
        print(line.replace(original, replacement))

    fileinput.close()

def find_in_file(filename, regexp):
    """search for regexp in file.
       If not found return false. If found return match.
    """
    with open(filename) as f:
        contents = f.read()

    try:
        # handle text files with \r\n line endings
        contents.index("\r", 0, 100)
        contents = contents.replace("\r\n", "\n")
    except ValueError:
        pass

    m = re.search(regexp, contents, re.MULTILINE)

    if not m: return False

    return m.group(0)

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


    def testBasicInteractive(self):
        # first command is an error that should be handled
        inputs = iter(["'quit", "quit"])

        orig_input = AdminTool.my_input

        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        self.install_init()
        self.admin=AdminTool()
        self.admin.settings['history_features'] = 2
        # set history_features to disable loading/saving history
        # and loading rc file. Otherwise file gets large and
        # breaks testing or overwrites the users history file.
        sys.argv=['main', '-i', self.dirname]

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip()
        
        print(ret)
        self.assertTrue(ret == 0)
        expected = 'ready for input.\nType "help" for help.'
        self.assertEqual(expected, out[-1*len(expected):])

        inputs = iter(["list user", "quit"])

        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip()
        
        print(ret)
        self.assertTrue(ret == 0)
        expected = 'help.\n   1: admin\n   2: anonymous'
        self.assertEqual(expected, out[-1*len(expected):])


        AdminTool.my_input = orig_input

    def testGet(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
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
            sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                      'title="bar foo bar"', 'assignedto=admin',
                      'superseder=1,2']
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '3')

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
            sys.argv=['main', '-i', self.dirname, '-d',
                      'get', 'assignedto',
                      'issue2' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, 'user2')
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-d', '-S', ':',
                      'get', 'assignedto',
                      'issue2' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, 'user2')
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
            sys.argv=['main', '-i', self.dirname, 'get', 'superseder',
                      'issue3' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, "['1', '2']")
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-d',
                      'get', 'superseder',
                      'issue3' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, "issue1\nissue2")
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-c', '-d',
                      'get', 'superseder',
                      'issue3' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out, "issue1,issue2")
        self.assertEqual(len(err), 0)

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-d',
                      'get', 'title',
                      'issue3' ]
            ret = self.admin.main()

        self.assertEqual(ret, 1)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        self.assertEqual(out.split('\n')[0], "Error: property title is not of type Multilink or Link so -d flag does not apply.")
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

        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'get', 'title', 'issue500']
            ret = self.admin.main()

        expected_err = 'Error: no such issue node "500"'

        self.assertEqual(ret, 1)
        out = out.getvalue().strip()
        err = err.getvalue().strip()
        print(out)
        self.assertEqual(out.index(expected_err), 0)
        self.assertEqual(len(err), 0)

    def testInit(self):
        self.admin=AdminTool()
        sys.argv=['main', '-i', self.dirname, 'install', 'classic', self.backend]
        ret = self.admin.main()
        print(ret)
        self.assertTrue(ret == 0)
        self.assertTrue(os.path.isfile(self.dirname + "/config.ini"))
        self.assertTrue(os.path.isfile(self.dirname + "/schema.py"))

        nopath= '/tmp/noSuchDirectory/nodir'
        norealpath = os.path.realpath(nopath + "/..")
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', nopath, 'install', 'classic', self.backend]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(ret)
        print(out)
        self.assertEqual(ret, 1)
        self.assertIn('Error: Instance home parent directory '
                      '"%s" does not exist' % norealpath, out)

    def testInitWithConfig_ini(self):
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
        self.assertEqual(config['MAIL_DEBUG'],
                         os.path.normpath(self.dirname + "/SendMail.LOG"))

    def testList(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        self.install_init()
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'list', 'user',
                      'username' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '1: admin\n   2: anonymous')

        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-c',
                      'list', 'user' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, '1,2')

        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-c',
                      'list', 'user', 'username' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, 'admin,anonymous')

        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-c',
                      'list', 'user', 'roles' ]
            ret = self.admin.main()

        self.assertEqual(ret, 0)
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, 'Admin,Anonymous')

        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'list', 'user',
                      'foo' ]
            ret = self.admin.main()

        self.assertEqual(ret, 1)
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out.split('\n')[0],
                         'Error: user has no property "foo"')


        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-c',
                      'list', 'user',
                      'bar' ]
            ret = self.admin.main()

        self.assertEqual(ret, 1)
        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out.split('\n')[0],
                         'Error: user has no property "bar"')

    def testFind(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
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

        # Reopen the db closed by previous filter call
        self.admin=AdminTool()
        with captured_output() as (out, err):
            ''' 1,2 should return all entries that have assignedto
                either admin or anonymous
            '''
            sys.argv=['main', '-i', self.dirname, '-c', '-d',
                      'find', 'issue', 'assignedto=admin,anonymous']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, "issue1,issue2")

        # Reopen the db closed by previous filter call
        self.admin=AdminTool()
        with captured_output() as (out, err):
            ''' 1,2 should return all entries that have assignedto
                either admin or anonymous
            '''
            sys.argv=['main', '-i', self.dirname, '-S', ':',
                      'find', 'issue', 'assignedto=admin,anonymous']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, "1:2")

    def testGenconfigUpdate(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import filecmp

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

    def testUpdateconfigPbkdf2(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        import filecmp

        self.admin=AdminTool()
        self.install_init()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'updateconfig',
                      self.dirname + "/config2.ini"]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        self.assertEqual(out, "")
        self.assertTrue(os.path.isfile(self.dirname + "/config2.ini"))
        # Autogenerated date header is different. Remove it
        # so filecmp passes.
        normalize_file(self.dirname + "/config2.ini",
                       [ '# Autogenerated at' ])
        normalize_file(self.dirname + "/config.ini",
                       [ '# Autogenerated at' ])

        self.assertTrue(filecmp.cmp(self.dirname + "/config.ini",
                                    self.dirname + "/config2.ini"))

        # Reopen the db closed by previous call
        self.admin=AdminTool()

        ### test replacement of old default value
        replace_in_file(self.dirname + "/config.ini",
                        "= 2000000", "= 10000")
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'update',
                      self.dirname + "/config2.ini"]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        expected = "from old default of 10000 to new default of 2000000."

        self.assertIn(expected, out)
        self.assertTrue(os.path.isfile(self.dirname + "/config2.ini"))
        self.assertEqual(find_in_file(self.dirname + "/config2.ini",
                                     "^password_.*= 2000000$"),
                         "password_pbkdf2_default_rounds = 2000000")

        # Reopen the db closed by previous call
        self.admin=AdminTool()

        ### test replacement of too small value
        replace_in_file(self.dirname + "/config.ini",
                        "= 10000", "= 10001")
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'update',
                      self.dirname + "/config2.ini"]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        expected = ("Update 'password_pbkdf2_default_rounds' to a number "
                    "equal to or larger\n  than 2000000.")

        self.assertIn(expected, out)
        self.assertTrue(os.path.isfile(self.dirname + "/config2.ini"))
        self.assertEqual(find_in_file(self.dirname + "/config2.ini",
                                     "^password_.*= 10001$"),
                         "password_pbkdf2_default_rounds = 10001")


        # Reopen the db closed by previous call
        self.admin=AdminTool()

        ### test no action if value is large enough
        replace_in_file(self.dirname + "/config.ini",
                        "= 10001", "= 2000001")
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'update',
                      self.dirname + "/config2.ini"]
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(out)
        expected = ""

        self.assertEqual(expected, out)
        self.assertTrue(os.path.isfile(self.dirname + "/config2.ini"))
        self.assertEqual(find_in_file(self.dirname + "/config2.ini",
                                     "^password_.*= 2000001$"),
                         "password_pbkdf2_default_rounds = 2000001")


    def testCliParse(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
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

        # Reopen the db closed by previous filter call
        # 
        # case: transitive property invalid match
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname,
                      '-d', 'filter', 'issue',
                      'assignedto.username=A']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print("me: " + out)
        print(err.getvalue().strip())
        self.assertEqual(out, "['issue1', 'issue2']")

    def testPragma_reopen_tracker(self):
        """test that _reopen_tracker works.
        """
        if self.backend not in ['anydbm']:
            self.skipTest("For speed only run test with anydbm.")

        orig_input = AdminTool.my_input

        # must set verbose to see _reopen_tracker hidden setting.
        # and to get "Reopening tracker" verbose log output
        inputs = iter(["pragma verbose=true", "pragma list", "quit"])
        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        self.install_init()
        self.admin=AdminTool()
        self.admin.settings['history_features'] = 2
        sys.argv=['main', '-i', self.dirname]

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip().split('\n')
        
        print(ret)
        self.assertTrue(ret == 0)
        expected = '   _reopen_tracker=False'
        self.assertIn(expected, out)
        self.assertIn('descriptions...', out[-1])
        self.assertNotIn('Reopening tracker', out)

        # -----
        inputs = iter(["pragma verbose=true", "pragma _reopen_tracker=True",
                       "pragma list", "quit"])
        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        self.install_init()
        self.admin=AdminTool()
        self.admin.settings['history_features'] = 2
        sys.argv=['main', '-i', self.dirname]

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip().split('\n')
        
        print(ret)
        self.assertTrue(ret == 0)
        self.assertEqual('Reopening tracker', out[2])
        expected = '   _reopen_tracker=True'
        self.assertIn(expected, out)

        # -----
        AdminTool.my_input = orig_input

    def testPragma(self):
        """Uses interactive mode since pragmas only apply when using multiple
           commands.
        """
        if self.backend not in ['anydbm']:
            self.skipTest("For speed only run test with anydbm.")

        orig_input = AdminTool.my_input

        for i in ["oN", "1", "yeS", "True"]:
            inputs = iter(["pragma verbose=%s" % i, "pragma list", "quit"])
            AdminTool.my_input = lambda _self, _prompt: next(inputs)

            self.install_init()
            self.admin=AdminTool()
            self.admin.settings['history_features'] = 2
            sys.argv=['main', '-i', self.dirname]

            with captured_output() as (out, err):
                ret = self.admin.main()

            out = out.getvalue().strip().split('\n')
        
            print(ret)
            self.assertTrue(ret == 0)
            expected = '   verbose=True'
            self.assertIn(expected, out)
            self.assertIn('descriptions...', out[-1])

        # -----
        for i in ["oFf", "0", "NO", "FalSe"]:
            inputs = iter(["pragma verbose=true", "pragma verbose=%s" % i,
                           "pragma list", "quit"])
            AdminTool.my_input = lambda _self, _prompt: next(inputs)

            self.install_init()
            self.admin=AdminTool()
            self.admin.settings['history_features'] = 2
            sys.argv=['main', '-i', self.dirname]

            with captured_output() as (out, err):
                ret = self.admin.main()

            out = out.getvalue().strip().split('\n')
        
            print(ret)
            self.assertTrue(ret == 0)
            expected = '   verbose=False'
            self.assertIn(expected, out)

        # -----  test syntax errors
        inputs = iter(["pragma", "pragma arg",
                       "pragma foo=3","quit"])
        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        self.install_init()
        self.admin=AdminTool()
        self.admin.settings['history_features'] = 2
        sys.argv=['main', '-i', self.dirname]

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip().split('\n')
        
        print(ret)
        self.assertTrue(ret == 0)
        expected = 'Error: Not enough arguments supplied'
        self.assertIn(expected, out)
        expected = 'Error: Argument must be setting=value, was given: arg.'
        self.assertIn(expected, out)
        expected = 'Error: Unknown setting foo. Try "pragma list".'
        self.assertIn(expected, out)

        # -----
        inputs = iter(["pragma verbose=foo", "quit"])
        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        self.install_init()
        self.admin=AdminTool()
        self.admin.settings['history_features'] = 2
        sys.argv=['main', '-i', self.dirname]

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip().split('\n')
        
        print(ret)
        self.assertTrue(ret == 0)
        expected = 'Error: Incorrect value for boolean setting verbose: foo.'
        self.assertIn(expected, out)

        # -----
        inputs = iter(["pragma verbose=on", "pragma _inttest=5",
                       "pragma list", "quit"])
        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        self.install_init()
        self.admin=AdminTool()
        self.admin.settings['history_features'] = 2
        sys.argv=['main', '-i', self.dirname]

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip().split('\n')
        
        print(ret)
        self.assertTrue(ret == 0)
        expected = '   _inttest=5'
        self.assertIn(expected, out)
        self.assertIn('descriptions...', out[-1])


        # -----
        inputs = iter(["pragma verbose=on", "pragma _inttest=fred",
                       "pragma list", "quit"])
        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        self.install_init()
        self.admin=AdminTool()
        self.admin.settings['history_features'] = 2
        sys.argv=['main', '-i', self.dirname]

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip().split('\n')
        
        print(ret)
        self.assertTrue(ret == 0)
        expected = 'Error: Incorrect value for integer setting _inttest: fred.'
        self.assertIn(expected, out)
        self.assertIn('descriptions...', out[-1])

        # -----
        inputs = iter(["pragma indexer_backend=whoosh", "pragma list",
                       "quit"])
        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        self.install_init()
        self.admin=AdminTool()
        self.admin.settings['history_features'] = 2
        sys.argv=['main', '-i', self.dirname]

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip().split('\n')
        
        print(ret)
        expected = '   indexer_backend=whoosh'
        self.assertIn(expected, out)

        # -----
        inputs = iter(["pragma _floattest=4.5", "quit"])
        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        self.install_init()
        self.admin=AdminTool()
        self.admin.settings['history_features'] = 2
        sys.argv=['main', '-i', self.dirname]

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip().split('\n')
        
        print(ret)
        expected = 'Error: Internal error: pragma can not handle values of type: float'
        self.assertIn(expected, out)


        # -----
        inputs = iter(["pragma display_protected=yes",
                       "display user1",
                       "quit"])
        AdminTool.my_input = lambda _self, _prompt: next(inputs)

        self.install_init()
        self.admin=AdminTool()
        self.admin.settings['history_features'] = 2
        sys.argv=['main', '-i', self.dirname]

        with captured_output() as (out, err):
            ret = self.admin.main()

        out = out.getvalue().strip()
        
        print(ret)
        expected = '\n*creation: '
        self.assertIn(expected, out)

        # -----
        AdminTool.my_input = orig_input

    def testReindex(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
        self.install_init()

        # create an issue
        self.admin=AdminTool()
        sys.argv=['main', '-i', self.dirname, 'create', 'issue',
                  'title="foo bar"', 'assignedto=admin' ]
        ret = self.admin.main()

        # reindex everything
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'reindex']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(len(out))
        print(repr(out))
        # make sure priority is being reindexed
        self.assertIn('Reindex priority 40%', out)


        # reindex whole class
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'reindex', 'issue']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(len(out))
        print(repr(out))
        self.assertEqual(out,
                         'Reindex issue  0%                                                          \rReindex issue 100%                                                         \rReindex issue done')
        self.assertEqual(len(out), 170)

        # reindex one item
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'reindex', 'issue1']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(len(out))
        print(repr(out))
        # no output when reindexing just one item
        self.assertEqual(out, '')

        # reindex range
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'reindex', 'issue:1-4']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(repr(out))
        self.assertIn('no such item "issue3"', out)

        # reindex bad class
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'reindex', 'issue1-4']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(repr(out))
        self.assertIn('Error: no such class "issue1-4"', out)

        # reindex bad item
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'reindex', 'issue14']
            ret = self.admin.main()

        out = out.getvalue().strip()
        print(repr(out))
        self.assertIn('Error: no such item "issue14"', out)

    def disabletestHelpInitopts(self):

        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
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

    def testSecurityListOne(self):
        self.install_init()
        self.admin=AdminTool()

        with captured_output() as (out, err):
            # make sure UsEr returns result for user. Roles are
            # lower cased interally
            sys.argv=['main', '-i', self.dirname, 'security', "user" ]
            ret = self.admin.main()

            result = """Role "user":
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


        # test 2 all role names are lower case, make sure
        # any role name is correctly lower cased
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'security', "UsEr" ]
            ret = self.admin.main()

        print(out.getvalue())

        self.assertEqual(result, out.getvalue())
        self.assertEqual(ret, 0)

        # test 3 Check error if role does not exist
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'security', "NoSuch Role" ]
            ret = self.admin.main()

        result='No such Role "NoSuch Role"\n'
        print('>', out.getvalue())

        self.assertEqual(result, out.getvalue())
        self.assertEqual(ret, 1)


    def testSecurityListAll(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
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

        # -----
        self.install_init()
        self.admin=AdminTool()

        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-P',
                      'display_protected=1', 'specification', 'user']
            ret = self.admin.main()

        outlist = out.getvalue().strip().split('\n')
        
        protected = [ 'id: <roundup.hyperdb.String>',
                      'creation: <roundup.hyperdb.Date>',
                      'activity: <roundup.hyperdb.Date>',
                      'creator: <roundup.hyperdb.Link to "user">',
                      'actor: <roundup.hyperdb.Link to "user">']
        print(outlist)
        self.assertEqual(sorted(outlist), sorted(spec + protected))

    def testRetireRestore(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
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

        # test show_retired pragma three cases:
        # no - no retired items
        # only - only retired items
        # both - all items

        # verify that user4 only is listed
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-P',
                      'show_retired=only', 'list', 'user']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(out)
        expected="4: user1"
        self.assertEqual(out, expected)

        # verify that all users are shown
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-P',
                      'show_retired=both', 'list', 'user']
            ret = self.admin.main()
        out_list = sorted(out.getvalue().strip().split("\n"))
        print(out)
        expected_list=sorted("1: admin\n   2: anonymous\n   3: user1\n   4: user1".split("\n"))
        self.assertEqual(out_list, expected_list)

        # verify that active users are shown
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-P',
                      'show_retired=no', 'list', 'user']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(out)
        expected="1: admin\n   2: anonymous\n   3: user1"
        self.assertEqual(out, expected)

        # test display headers for retired/active
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, '-P',
                      'display_header=yes', 'display', 'user3,user4']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(out)
        self.assertIn("[user3 (active)]\n", out)
        self.assertIn( "[user4 (retired)]\n", out)

        # test that there are no headers
        self.admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'display', 'user3,user4']
            ret = self.admin.main()
        out = out.getvalue().strip()
        print(out)
        self.assertNotIn("user3", out)
        self.assertNotIn("user4", out)

    def testTable(self):
        ''' Note the tests will fail if you run this under pdb.
            the context managers capture the pdb prompts and this screws
            up the stdout strings with (pdb) prefixed to the line.
        '''
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

    def testTemplates(self):
        
        self.install_init()
        self.admin=AdminTool()

        with captured_output() as (out, err):
            # command does not require a tracker home. use missing zZzZ
            # directory to cause error if that changes
            sys.argv=['main', '-i', "zZzZ", 'templates' ]
            ret = self.admin.main()

        out = out.getvalue().strip()

        # all 5 standard trackers should be found
        for tracker in ['Name: classic\nPath:',
                        'Name: devel\nPath:',
                        'Name: jinja2\nPath:',
                        'Name: minimal\nPath:',
                        'Name: responsive\nPath:']:
            self.assertIn(tracker, out)

        with captured_output() as (out, err):
            # command does not require a tracker home. use missing zZzZ
            # directory to cause error if that changes
            sys.argv=['main', '-i', "zZzZ", 'templates', 'trace_search' ]
            ret = self.admin.main()

        out = out.getvalue().strip()

        expected = "/*\n"
        self.assertIn(expected, out)

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
