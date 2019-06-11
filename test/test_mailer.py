#-*- encoding: utf-8 -*-
import unittest

from roundup import mailer

class EncodingTestCase(unittest.TestCase):
    def testEncoding(self):
        a = lambda n, a, c, o: self.assertEqual(mailer.nice_sender_header(n,
            a, c), o)
        a('ascii', 'ascii@test.com', 'iso8859-1', 'ascii <ascii@test.com>')
        a(u'café', 'ascii@test.com', 'iso8859-1',
            '=?iso8859-1?q?caf=E9?= <ascii@test.com>')
        a(u'café', 'ascii@test.com', 'utf-8',
            '=?utf-8?b?Y2Fmw6k=?= <ascii@test.com>')
        a('as"ii', 'ascii@test.com', 'iso8859-1', '"as\\"ii" <ascii@test.com>')

# vim: set et sts=4 sw=4 :
