import unittest
import os, sys, shutil

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

class TestDemo(unittest.TestCase):
    def setUp(self):
        self.home = os.path.abspath('_test_demo')

    def tearDown(self):
        try:
            shutil.rmtree(self.home)
        except FileNotFoundError:
            pass
        
    def testDemo(self):
        with captured_output() as (out, err):
            install_demo(self.home, 'anydbm', 'classic')
        output = out.getvalue().strip()
        print(output)

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


