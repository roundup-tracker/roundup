#
# Copyright (c) 2003 Richard Jones, richard@commonground.com.au
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# $Id: test_hyperdbvals.py,v 1.3 2006-08-18 01:26:19 richard Exp $

import unittest, os, shutil, errno, sys, difflib, cgi, re, sha

from roundup import init, instance, password, hyperdb, date

class TestClass:
    def getprops(self):
        return {
            'string': hyperdb.String(),
            'number': hyperdb.Number(),
            'boolean': hyperdb.Boolean(),
            'password': hyperdb.Password(),
            'date': hyperdb.Date(),
            'interval': hyperdb.Interval(),
            'link': hyperdb.Link('test'),
            'link2': hyperdb.Link('test2'),
            'multilink': hyperdb.Multilink('test'),
            'multilink2': hyperdb.Multilink('test2'),
        }
    def getkey(self):
        return 'string'
    def lookup(self, value):
        if value == 'valid':
            return '1'
        raise KeyError
    def get(self, nodeid, propname):
        assert propname.startswith('multilink')
        assert nodeid is not None
        return ['2', '3']

class TestClass2:
    def properties(self):
        return {
            'string': hyperdb.String(),
        }
    def getkey(self):
        return None
    def labelprop(self, default_to_id=1):
        return 'id'

class TestDatabase:
    classes = {'test': TestClass(), 'test2': TestClass2()}
    def getUserTimezone(self):
        return 0

class RawToHyperdbTest(unittest.TestCase):
    def _test(self, propname, value, itemid=None):
        return hyperdb.rawToHyperdb(TestDatabase(), TestClass(), itemid,
            propname, value)
    def testString(self):
        self.assertEqual(self._test('password', ''), None)
        self.assertEqual(self._test('string', '  a string '), 'a string')
    def testNumber(self):
        self.assertEqual(self._test('password', ''), None)
        self.assertEqual(self._test('number', '  10 '), 10)
        self.assertEqual(self._test('number', '  1.5 '), 1.5)
    def testBoolean(self):
        self.assertEqual(self._test('password', ''), None)
        for true in 'yes true on 1'.split():
            self.assertEqual(self._test('boolean', '  %s '%true), 1)
        for false in 'no false off 0'.split():
            self.assertEqual(self._test('boolean', '  %s '%false), 0)
    def testPassword(self):
        self.assertEqual(self._test('password', ''), None)
        self.assertEqual(self._test('password', '  a string '), 'a string')
        val = self._test('password', '  a string ')
        self.assert_(isinstance(val, password.Password))
        val = self._test('password', '{plaintext}a string')
        self.assert_(isinstance(val, password.Password))
        val = self._test('password', '{crypt}a string')
        self.assert_(isinstance(val, password.Password))
        s = sha.sha('a string').hexdigest()
        val = self._test('password', '{SHA}'+s)
        self.assert_(isinstance(val, password.Password))
        self.assertEqual(val, 'a string')
        self.assertRaises(hyperdb.HyperdbValueError, self._test,
            'password', '{fubar}a string')
    def testDate(self):
        self.assertEqual(self._test('password', ''), None)
        val = self._test('date', ' 2003-01-01  ')
        self.assert_(isinstance(val, date.Date))
        val = self._test('date', ' 2003/01/01  ')
        self.assert_(isinstance(val, date.Date))
        val = self._test('date', ' 2003/1/1  ')
        self.assert_(isinstance(val, date.Date))
        val = self._test('date', ' 2003-1-1  ')
        self.assert_(isinstance(val, date.Date))
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'date',
            'fubar')
    def testInterval(self):
        self.assertEqual(self._test('password', ''), None)
        val = self._test('interval', ' +1d  ')
        self.assert_(isinstance(val, date.Interval))
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'interval',
            'fubar')
    def testLink(self):
        self.assertEqual(self._test('password', ''), None)
        self.assertEqual(self._test('link', '1'), '1')
        self.assertEqual(self._test('link', 'valid'), '1')
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'link',
            'invalid')
    def testMultilink(self):
        self.assertEqual(self._test('multilink', '', '1'), [])
        self.assertEqual(self._test('multilink', '1', '1'), ['1'])
        self.assertEqual(self._test('multilink', 'valid', '1'), ['1'])
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'multilink',
            'invalid', '1')
        self.assertEqual(self._test('multilink', '+1', '1'), ['1', '2', '3'])
        self.assertEqual(self._test('multilink', '+valid', '1'), ['1', '2',
            '3'])
        self.assertEqual(self._test('multilink', '+1,-2', '1'), ['1', '3'])
        self.assertEqual(self._test('multilink', '+valid,-3', '1'), ['1', '2'])
        self.assertEqual(self._test('multilink', '+1', None), ['1'])
        self.assertEqual(self._test('multilink', '+valid', None), ['1'])
        self.assertEqual(self._test('multilink', '', None), [])

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(RawToHyperdbTest))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)
# vim: set filetype=python ts=4 sw=4 et si
