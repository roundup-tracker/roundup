#-*- encoding: utf-8 -*-
""" Testing the jinja2 templating engine of roundup-tracker.

Copyright: 2016 Intevation GmbH.
Author: Bernhard E. Reiter <bernhard@intevation.de>

This module is Free Software under the Roundup licensing of 1.5,
see the COPYING.txt file coming with Roundup.

Just a test file template for now.
"""
import shutil # only, needed for tearDown. TODO: Remove when refactored.
import unittest

from . import db_test_base

TESTSUITE_IDENTIFIER='jinja2'

class TestCase_Zero(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(True, True)


class Jinja2Test(object):
    """Sets up and tears down an instance with database contents.

    Setup and teardown modelled after the use of db_test_base
    by several modules like test_xmlrpc and test_userauditor.

    TODO: Should probably be moved to a base case in db_test_base.py.
    """

    backend = None  # can be used to create tests per backend, see test_xmlrpc

    def setUp(self):
        self.dirname = '_test_' + TESTSUITE_IDENTIFIER
        self.instance = db_test_base.setupTracker(self.dirname, self.backend)
        self.db = self.instance.open('admin')

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def test_zero(self):
        """Do nothing just make sure that setup and teardown works."""
        pass


# only using one database backend for now, not sure if doing all
# backends will keep the test focussed enough to be useful for the used
# computing time. Would be okay to change in the future.
class anydbmJinja2Test(Jinja2Test, unittest.TestCase):
    backend = 'anydbm'

# vim: ts=4 et sts=4 sw=4 ai :


