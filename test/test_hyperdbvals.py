#
# Copyright (c) 2003 Richard Jones, richard@commonground.com.au
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

import unittest, os, shutil, errno, sys, difflib, cgi, re
from hashlib import sha1

from roundup import init, instance, password, hyperdb, date

class TestClass:
    def getprops(self):
        return {
            'string': hyperdb.String(),
            'number': hyperdb.Number(),
            'integer': hyperdb.Integer(),
            'boolean': hyperdb.Boolean(),
            'password': hyperdb.Password(),
            'date': hyperdb.Date(),
            'interval': hyperdb.Interval(),
            'link': hyperdb.Link('test'),
            'linkkeyonly': hyperdb.Link('test', try_id_parsing='no'),
            'link2': hyperdb.Link('test2'),
            'multilink': hyperdb.Multilink('test'),
            'multilink2': hyperdb.Multilink('test2'),
            'multilink3': hyperdb.Multilink('test', try_id_parsing='no'),
        }
    def getkey(self):
        return 'string'
    def lookup(self, value):
        if value == 'valid':
            return '1'
        if value == '2valid':
            return '2'
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
        self.assertEqual(self._test('number', '  -1022.5 '), -1022.5)
    def testInteger(self):
        self.assertEqual(self._test('integer', '  100 '), 100)
        self.assertEqual(self._test('integer', '  0 '), 0)
        self.assertEqual(self._test('integer', '  -100 '), -100)
        # make sure error raised on string
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'integer', 'a string', 'a string')
        # make sure error raised on real number
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'integer', '  -100.2 ')
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
        self.assertTrue(isinstance(val, password.Password))
        val = self._test('password', '{plaintext}a string')
        self.assertTrue(isinstance(val, password.Password))
        val = self._test('password', '{crypt}a string')
        self.assertTrue(isinstance(val, password.Password))
        s = sha1(b'a string').hexdigest()
        val = self._test('password', '{SHA}'+s)
        self.assertTrue(isinstance(val, password.Password))
        self.assertEqual(val, 'a string')
        self.assertRaises(hyperdb.HyperdbValueError, self._test,
            'password', '{fubar}a string')
    def testDate(self):
        self.assertEqual(self._test('password', ''), None)
        val = self._test('date', ' 2003-01-01  ')
        self.assertTrue(isinstance(val, date.Date))
        val = self._test('date', ' 2003/01/01  ')
        self.assertTrue(isinstance(val, date.Date))
        val = self._test('date', ' 2003/1/1  ')
        self.assertTrue(isinstance(val, date.Date))
        val = self._test('date', ' 2003-1-1  ')
        self.assertTrue(isinstance(val, date.Date))
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'date',
            'fubar')
    def testInterval(self):
        self.assertEqual(self._test('password', ''), None)
        val = self._test('interval', ' +1d  ')
        self.assertTrue(isinstance(val, date.Interval))
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'interval',
            'fubar')
    def testLink(self):
        self.assertEqual(self._test('link', '1'), '1')
        self.assertEqual(self._test('link', 'valid'), '1')
        self.assertEqual(self._test('linkkeyonly', 'valid'), '1')
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'link',
            'invalid')
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'linkkeyonly',
            '1')
        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'linkkeyonly',
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

    def testMultilink3(self):
        # note that all +1, -2 type references will fail with exceptions
        # '+1' is an id and try_id_parsing is set to no for multilink3
        # and the 'name/key' 1 or 2 doesn't exist.

        self.assertEqual(self._test('multilink3', '', '1'), [])

        with self.assertRaises(hyperdb.HyperdbValueError) as cm:
            self._test('multilink3', '1', '1')
        self.assertEqual(cm.exception.args,
                         ("property multilink3: '1' is not a test.",))

        self.assertEqual(self._test('multilink3', 'valid', '1'), ['1'])

        self.assertRaises(hyperdb.HyperdbValueError, self._test, 'multilink3',
            'invalid', '1')

        with self.assertRaises(hyperdb.HyperdbValueError) as cm:
            self._test('multilink3', '+1', '1')
        self.assertEqual(cm.exception.args,
                         ("property multilink3: '1' is not a test.",))

        self.assertEqual(self._test('multilink3', '+valid', '1'),
                         ['1', '2', '3'])

        with self.assertRaises(hyperdb.HyperdbValueError) as cm:
            self._test('multilink3', '+1,-2', '1')
        self.assertEqual(cm.exception.args,
                         ("property multilink3: '1' is not a test.",))

        with self.assertRaises(hyperdb.HyperdbValueError) as cm:
            self._test('multilink3', '+valid,-2', '1')
        self.assertEqual(cm.exception.args,
                         ("property multilink3: '2' is not a test.",))

        self.assertEqual(self._test('multilink3', '+valid,-2valid', '1'), ['1', '3'])

        self.assertEqual(self._test('multilink3', '+valid', None), ['1'])

        self.assertEqual(self._test('multilink3', '', None), [])

        self.assertEqual(self._test('multilink3', '-valid', None), [])

# vim: set filetype=python ts=4 sw=4 et si
