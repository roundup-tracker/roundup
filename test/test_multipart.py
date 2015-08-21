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

import unittest
from cStringIO import StringIO

from roundup.mailgw import Message

class ExampleMessage(Message):
    # A note on message/rfc822: The content of such an attachment is an
    # email with at least one header line. RFC2046 tells us: """   A
    # media type of "message/rfc822" indicates that the body contains an
    # encapsulated message, with the syntax of an RFC 822 message.
    # However, unlike top-level RFC 822 messages, the restriction that
    # each "message/rfc822" body must include a "From", "Date", and at
    # least one destination header is removed and replaced with the
    # requirement that at least one of "From", "Subject", or "Date" must
    # be present."""
    # This means we have to add a newline after the mime-header before
    # the subject, otherwise the subject is part of the mime header not
    # part of the email header.
    table = {'multipart/signed': '    boundary="boundary-%(indent)s";\n',
             'multipart/mixed': '    boundary="boundary-%(indent)s";\n',
             'multipart/alternative': '    boundary="boundary-%(indent)s";\n',
             'text/plain': '    name="foo.txt"\nfoo\n',
             'application/pgp-signature': '    name="foo.gpg"\nfoo\n',
             'application/pdf': '    name="foo.pdf"\nfoo\n',
             'message/rfc822': '\nSubject: foo\n\nfoo\n'}

    def __init__(self, spec):
        """Create a basic MIME message according to 'spec'.

        Each line of a spec has one content-type, which is optionally indented.
        The indentation signifies how deep in the MIME hierarchy the
        content-type is.

        """
        parts = []
        for line in spec.splitlines():
            content_type = line.strip()
            if not content_type:
                continue

            indent = self.getIndent(line)
            if indent:
                parts.append('\n--boundary-%s\n' % indent)
            parts.append('Content-type: %s;\n' % content_type)
            parts.append(self.table[content_type] % {'indent': indent + 1})

        Message.__init__(self, StringIO(''.join(parts)))

    def getIndent(self, line):
        """Get the current line's indentation, using four-space indents."""
        count = 0
        for char in line:
            if char != ' ':
                break
            count += 1
        return count / 4

class MultipartTestCase(unittest.TestCase):
    def setUp(self):
        self.fp = StringIO()
        w = self.fp.write
        w('Content-Type: multipart/mixed; boundary="foo"\r\n\r\n')
        w('This is a multipart message. Ignore this bit.\r\n')
        w('\r\n--foo\r\n')

        w('Content-Type: text/plain\r\n\r\n')
        w('Hello, world!\r\n')
        w('\r\n')
        w('Blah blah\r\n')
        w('foo\r\n')
        w('-foo\r\n')
        w('\r\n--foo\r\n')

        w('Content-Type: multipart/alternative; boundary="bar"\r\n\r\n')
        w('This is a multipart message. Ignore this bit.\r\n')
        w('\r\n--bar\r\n')

        w('Content-Type: text/plain\r\n\r\n')
        w('Hello, world!\r\n')
        w('\r\n')
        w('Blah blah\r\n')
        w('\r\n--bar\r\n')

        w('Content-Type: text/html\r\n\r\n')
        w('<b>Hello, world!</b>\r\n')
        w('\r\n--bar--\r\n')
        w('\r\n--foo\r\n')

        w('Content-Type: text/plain\r\n\r\n')
        w('Last bit\n')
        w('\r\n--foo--\r\n')
        self.fp.seek(0)

    def testMultipart(self):
        m = Message(self.fp)
        self.assert_(m is not None)

        # skip the first bit
        p = m.getpart()
        self.assert_(p is not None)
        self.assertEqual(p.fp.read(),
            'This is a multipart message. Ignore this bit.\r\n')

        # first text/plain
        p = m.getpart()
        self.assert_(p is not None)
        self.assertEqual(p.gettype(), 'text/plain')
        self.assertEqual(p.fp.read(),
            'Hello, world!\r\n\r\nBlah blah\r\nfoo\r\n-foo\r\n')

        # sub-multipart
        p = m.getpart()
        self.assert_(p is not None)
        self.assertEqual(p.gettype(), 'multipart/alternative')

        # sub-multipart text/plain
        q = p.getpart()
        self.assert_(q is not None)
        q = p.getpart()
        self.assert_(q is not None)
        self.assertEqual(q.gettype(), 'text/plain')
        self.assertEqual(q.fp.read(), 'Hello, world!\r\n\r\nBlah blah\r\n')

        # sub-multipart text/html
        q = p.getpart()
        self.assert_(q is not None)
        self.assertEqual(q.gettype(), 'text/html')
        self.assertEqual(q.fp.read(), '<b>Hello, world!</b>\r\n')

        # sub-multipart end
        q = p.getpart()
        self.assert_(q is None)

        # final text/plain
        p = m.getpart()
        self.assert_(p is not None)
        self.assertEqual(p.gettype(), 'text/plain')
        self.assertEqual(p.fp.read(),
            'Last bit\n')

        # end
        p = m.getpart()
        self.assert_(p is None)

    def TestExtraction(self, spec, expected):
        self.assertEqual(ExampleMessage(spec).extract_content(), expected)

    def testTextPlain(self):
        self.TestExtraction('text/plain', ('foo\n', []))

    def testAttachedTextPlain(self):
        self.TestExtraction("""
multipart/mixed
    text/plain
    text/plain""",
                  ('foo\n',
                   [('foo.txt', 'text/plain', 'foo\n')]))

    def testMultipartMixed(self):
        self.TestExtraction("""
multipart/mixed
    text/plain
    application/pdf""",
                  ('foo\n',
                   [('foo.pdf', 'application/pdf', 'foo\n')]))

    def testMultipartAlternative(self):
        self.TestExtraction("""
multipart/alternative
    text/plain
    application/pdf
""", ('foo\n', [('foo.pdf', 'application/pdf', 'foo\n')]))

    def testDeepMultipartAlternative(self):
        self.TestExtraction("""
multipart/mixed
    multipart/alternative
        text/plain
        application/pdf
""", ('foo\n', [('foo.pdf', 'application/pdf', 'foo\n')]))

    def testSignedText(self):
        self.TestExtraction("""
multipart/signed
    text/plain
    application/pgp-signature""", ('foo\n', []))

    def testSignedAttachments(self):
        self.TestExtraction("""
multipart/signed
    multipart/mixed
        text/plain
        application/pdf
    application/pgp-signature""",
                  ('foo\n',
                   [('foo.pdf', 'application/pdf', 'foo\n')]))

    def testAttachedSignature(self):
        self.TestExtraction("""
multipart/mixed
    text/plain
    application/pgp-signature""",
                  ('foo\n',
                   [('foo.gpg', 'application/pgp-signature', 'foo\n')]))

    def testMessageRfc822(self):
        self.TestExtraction("""
multipart/mixed
    message/rfc822""",
                  (None,
                   [('foo.eml', 'message/rfc822', 'Subject: foo\n\nfoo\n')]))

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(MultipartTestCase))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)


# vim: set filetype=python ts=4 sw=4 et si
