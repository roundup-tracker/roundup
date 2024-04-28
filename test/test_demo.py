import pytest
import unittest
import os, sys, shutil

from os.path import normpath

from roundup.demo import install_demo, run_demo

import roundup.scripts.roundup_server

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

try:
    import jinja2
    skip_jinja2 = lambda func, *args, **kwargs: func
except ImportError:
    from .pytest_patcher import mark_class
    skip_jinja2 = mark_class(pytest.mark.skip(
        reason='Skipping Jinja2 tests: jinja2 library not available'))

class TestDemo(unittest.TestCase):
    def setUp(self):
        self.home = os.path.abspath('_test_demo')

    def tearDown(self):
        try:
            shutil.rmtree(self.home)
        except FileNotFoundError:
            pass
        
    def run_install_demo(self, template, db="anydbm"):
        with captured_output() as (out, err):
            install_demo(self.home, db, template)
        output = out.getvalue().strip()
        print(output)

        # verify that db was set properly by reading config
        with open(self.home + "/config.ini", "r") as f:
            config_lines = f.read().replace("\r\n", "\n")

        try:
            # handle text files with \r\n line endings
            config_lines.index("\r", 0, 100)
            config_lines = config_lines.replace("\r\n", "\n")
        except ValueError:
            pass

        self.assertIn("backend = %s\n"%db, config_lines)

        # dummy up the return of get_server so the serve_forever method
        # raises keyboard interrupt exiting the server so the test exits.
        gs = roundup.scripts.roundup_server.ServerConfig.get_server
        def raise_KeyboardInterrupt():
            raise KeyboardInterrupt

        def test_get_server(self):
            httpd = gs(self)
            httpd.serve_forever = raise_KeyboardInterrupt
            return httpd

        roundup.scripts.roundup_server.ServerConfig.get_server = test_get_server

        # Run under context manager to capture output of startup text.
        with captured_output() as (out, err):
            run_demo(self.home)
        output = out.getvalue().strip()
        print(output)
        # if the server installed and started this will be the
        # last line in the output.
        self.assertIn("Keyboard Interrupt: exiting", output.split('\n'))

    def testDemoClassic(self):
        with captured_output() as (out, err):
            self.run_install_demo("classic")
        self.assertIn("http://localhost:8917/demo/", out.getvalue())

        # verify the default anydbm db is created
        db_file = self.home + normpath("/db/nodes.user")
        db_file_dumbdbm = self.home + normpath("/db/nodes.user.dir")
        self.assertTrue(os.path.isfile(db_file) or
                        os.path.isfile(db_file_dumbdbm),
                        "expected db file %s or %s does not exist" % (
                            db_file, db_file_dumbdbm
                        ))

         # verify requested template was used
        with open(self.home + "/TEMPLATE-INFO.txt", "r") as f:
            info_lines = f.read()

        try:
            # handle text files with \r\n line endings
            info_lines.index("\r", 0, 100)
            info_lines = info_lines.replace("\r\n", "\n")
        except ValueError:
            pass

        self.assertIn("Name: classic-_test_demo\n", info_lines)

    def testDemoMinimal(self):
        # test explicit path to template as others test template
        # search path.
        with captured_output() as (out, err):
            self.run_install_demo('../templates/minimal', db="sqlite")
        self.assertIn("http://localhost:8917/demo/", out.getvalue())

        # verify the requested sqlite db file is created
        db_file = self.home + "/db/db"
        self.assertTrue(os.path.isfile(db_file),
                        "expected db file %s does not exist" % db_file)

        # verify requested template was used
        with open(self.home + "/TEMPLATE-INFO.txt", "r") as f:
            info_lines = f.read()

        try:
            # handle text files with \r\n line endings
            info_lines.index("\r", 0, 100)
            info_lines = info_lines.replace("\r\n", "\n")
        except ValueError:
            pass

        self.assertIn("Name: minimal-_test_demo\n", info_lines)

    @skip_jinja2
    def testDemoJinja(self):
        with captured_output() as (out, err):
            self.run_install_demo('jinja2', db="anydbm")
        self.assertIn("http://localhost:8917/demo/", out.getvalue())

        # verify the requested anydbm db file is created
        db_file = self.home + "/db/nodes.user"
        self.assertTrue(os.path.isfile(db_file),
                        "expected db file %s does not exist" % db_file)

        # verify that template was set to jinja2 by reading config
        with open(self.home + "/config.ini", "r") as f:
            config_lines = f.read()

        try:
            # handle text files with \r\n line endings
            config_lines.index("\r", 0, 100)
            config_lines = config_lines.replace("\r\n", "\n")
        except ValueError:
            pass

        self.assertIn("template_engine = jinja2\n", config_lines)

