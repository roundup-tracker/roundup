#-*- encoding: utf8 -*-
import unittest

from roundup import mailer

class EncodingTestCase(unittest.TestCase):
    def testEncoding(self):
        a = lambda n, a, c, o: self.assertEquals(mailer.nice_sender_header(n,
            a, c), o)
        a('ascii', 'ascii@test.com', 'iso8859-1', 'ascii <ascii@test.com>')
        a(u'café', 'ascii@test.com', 'iso8859-1',
            '=?iso8859-1?q?caf=E9?= <ascii@test.com>')
        a('as"ii', 'ascii@test.com', 'iso8859-1', '"as\\"ii" <ascii@test.com>')

# vim: set et sts=4 sw=4 :
