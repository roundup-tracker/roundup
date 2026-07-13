#-*- encoding: utf-8 -*-
import sys
import unittest

from roundup import mailer

class EncodingTestCase(unittest.TestCase):
    def testEncoding(self):
        a = lambda n, a, c, o: self.assertEqual(mailer.nice_sender_header(n,
            a, c), o)
        a('ascii', 'ascii@test.com', 'iso8859-1', 'ascii <ascii@test.com>')
        # FIXME 3.15 remove else case as it will not be needed anymore.
        if sys.version_info >= (3, 15, 0):
            a(u'café', 'ascii@test.com', 'iso8859-1',
              '=?iso-8859-1?q?caf=E9?= <ascii@test.com>')
        else:
            a(u'café', 'ascii@test.com', 'iso8859-1',
              '=?iso8859-1?q?caf=E9?= <ascii@test.com>')
        a(u'café', 'ascii@test.com', 'utf-8',
            '=?utf-8?b?Y2Fmw6k=?= <ascii@test.com>')
        a('as"ii', 'ascii@test.com', 'iso8859-1', '"as\\"ii" <ascii@test.com>')

# vim: set et sts=4 sw=4 :
