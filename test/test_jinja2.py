#-*- encoding: utf8 -*-
""" Testing the jinja2 templating engine of roundup-tracker.

Copyright 2015 Bernhard E. Reiter <bernhard@intevation.de>
This module is Free Software under the Roundup licensing of 1.5,
see the COPYING.txt file coming with Roundup.

Just a test file template for now.
"""
import unittest

import db_test_base

TESTSUITE_IDENTIFIER='jinja2'

class TestCase_Zero(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(True, True)

class TestCase(unittest.TestCase):

    backend = None  # can be used to create tests per backend, see test_xmlrpc

    def setUp(self):
        self.dirname = '_test_' + TESTSUITE_IDENTIFIER
        self.instance = db_test_base.setupTracker(self.dirname, self.backend)
        self.db = self.instance.open('admin')

    def test_zero(self):
        pass

def test_suite():
    suite = unittest.TestSuite()

    suite.addTest(unittest.makeSuite(TestCase_Zero))

    # only using one database backend for now, not sure if doing all
    # backends will keep the test focussed enough to be useful for the used
    # computing time. Would be okay to change in the future.
    l = 'anydbm'
    dct = dict(backend = l)
    subcls = type(TestCase)('TestCase_%s'%l, (TestCase,), dct)
    suite.addTest(unittest.makeSuite(subcls))

    return suite

# Other roundup testcases do have a def main thing in there,
# but I'm not sure if this is still helpful. So left out for now.

# vim: ts=4 et sts=4 sw=4 ai :


