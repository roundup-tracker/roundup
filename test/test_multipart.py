#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
# $Id: test_multipart.py,v 1.6 2003-10-25 22:53:26 richard Exp $ 

import unittest, cStringIO

from roundup.mailgw import Message

class MultipartTestCase(unittest.TestCase):
    def setUp(self):
        self.fp = cStringIO.StringIO()
        w = self.fp.write
        w('Content-Type: multipart/mixed; boundary="foo"\r\n\r\n')
        w('This is a multipart message. Ignore this bit.\r\n')
        w('--foo\r\n')

        w('Content-Type: text/plain\r\n\r\n')
        w('Hello, world!\r\n')
        w('\r\n')
        w('Blah blah\r\n')
        w('foo\r\n')
        w('-foo\r\n')
        w('--foo\r\n')

        w('Content-Type: multipart/alternative; boundary="bar"\r\n\r\n')
        w('This is a multipart message. Ignore this bit.\r\n')
        w('--bar\r\n')

        w('Content-Type: text/plain\r\n\r\n')
        w('Hello, world!\r\n')
        w('\r\n')
        w('Blah blah\r\n')
        w('--bar\r\n')

        w('Content-Type: text/html\r\n\r\n')
        w('<b>Hello, world!</b>\r\n')
        w('--bar--\r\n')
        w('--foo\r\n')

        w('Content-Type: text/plain\r\n\r\n')
        w('Last bit\n')
        w('--foo--\r\n')
        self.fp.seek(0)

    def testMultipart(self):
        m = Message(self.fp)
        self.assert_(m is not None)

        # skip the first bit
        p = m.getPart()
        self.assert_(p is not None)
        self.assertEqual(p.fp.read(),
            'This is a multipart message. Ignore this bit.\r\n')

        # first text/plain
        p = m.getPart()
        self.assert_(p is not None)
        self.assertEqual(p.gettype(), 'text/plain')
        self.assertEqual(p.fp.read(),
            'Hello, world!\r\n\r\nBlah blah\r\nfoo\r\n-foo\r\n')

        # sub-multipart
        p = m.getPart()
        self.assert_(p is not None)
        self.assertEqual(p.gettype(), 'multipart/alternative')

        # sub-multipart text/plain
        q = p.getPart()
        self.assert_(q is not None)
        q = p.getPart()
        self.assert_(q is not None)
        self.assertEqual(q.gettype(), 'text/plain')
        self.assertEqual(q.fp.read(), 'Hello, world!\r\n\r\nBlah blah\r\n')

        # sub-multipart text/html
        q = p.getPart()
        self.assert_(q is not None)
        self.assertEqual(q.gettype(), 'text/html')
        self.assertEqual(q.fp.read(), '<b>Hello, world!</b>\r\n')

        # sub-multipart end
        q = p.getPart()
        self.assert_(q is None)

        # final text/plain
        p = m.getPart()
        self.assert_(p is not None)
        self.assertEqual(p.gettype(), 'text/plain')
        self.assertEqual(p.fp.read(),
            'Last bit\n')

        # end
        p = m.getPart()
        self.assert_(p is None)

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(MultipartTestCase))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)


# vim: set filetype=python ts=4 sw=4 et si
