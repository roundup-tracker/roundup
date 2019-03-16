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

import email
import unittest
from roundup.anypy.strings import StringIO

from roundup.mailgw import RoundupMessage

def gen_message(spec):
    """Create a basic MIME message according to 'spec'.

    Each line of a spec has one content-type, which is optionally indented.
    The indentation signifies how deep in the MIME hierarchy the
    content-type is.

    """

    def getIndent(line):
        """Get the current line's indentation, using four-space indents."""
        count = 0
        for char in line:
            if char != ' ':
                break
            count += 1
        return count // 4

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
             'text/html': '    name="bar.html"\n<html><body>bar &gt;</body></html>\n',
             'application/pgp-signature': '    name="foo.gpg"\nfoo\n',
             'application/pdf': '    name="foo.pdf"\nfoo\n',
             'message/rfc822': '\nSubject: foo\n\nfoo\n'}

    parts = []
    for line in spec.splitlines():
        content_type = line.strip()
        if not content_type:
            continue

        indent = getIndent(line)
        if indent:
            parts.append('\n--boundary-%s\n' % indent)
        parts.append('Content-type: %s;\n' % content_type)
        parts.append(table[content_type] % {'indent': indent + 1})

    for i in range(indent, 0, -1):
        parts.append('\n--boundary-%s--\n' % i)

    return email.message_from_file(StringIO(''.join(parts)), RoundupMessage)

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
        m = email.message_from_file(self.fp, RoundupMessage)
        self.assertTrue(m is not None)

        it = iter(m.get_payload())

        # first text/plain
        p = next(it, None)
        self.assertTrue(p is not None)
        self.assertEqual(p.get_content_type(), 'text/plain')
        self.assertEqual(p.get_payload(),
            'Hello, world!\r\n\r\nBlah blah\r\nfoo\r\n-foo\r\n')

        # sub-multipart
        p = next(it, None)
        self.assertTrue(p is not None)
        self.assertEqual(p.get_content_type(), 'multipart/alternative')

        # sub-multipart text/plain
        qit = iter(p.get_payload())
        q = next(qit, None)
        self.assertTrue(q is not None)
        self.assertEqual(q.get_content_type(), 'text/plain')
        self.assertEqual(q.get_payload(), 'Hello, world!\r\n\r\nBlah blah\r\n')

        # sub-multipart text/html
        q = next(qit, None)
        self.assertTrue(q is not None)
        self.assertEqual(q.get_content_type(), 'text/html')
        self.assertEqual(q.get_payload(), '<b>Hello, world!</b>\r\n')

        # sub-multipart end
        q = next(qit, None)
        self.assertTrue(q is None)

        # final text/plain
        p = next(it, None)
        self.assertTrue(p is not None)
        self.assertEqual(p.get_content_type(), 'text/plain')
        self.assertEqual(p.get_payload(),
            'Last bit\n')

        # end
        p = next(it, None)
        self.assertTrue(p is None)

    def TestExtraction(self, spec, expected, convert_html_with=False):
        if convert_html_with:
            from roundup.dehtml import dehtml
            html2text=dehtml(convert_html_with).html2text
        else:
            html2text=None

        self.assertEqual(gen_message(spec).extract_content(
            html2text=html2text), expected)

    def testTextPlain(self):
        self.TestExtraction('text/plain', ('foo\n', [], False))

    def testAttachedTextPlain(self):
        self.TestExtraction("""
multipart/mixed
    text/plain
    text/plain""",
                  ('foo\n',
                   [('foo.txt', 'text/plain', 'foo\n')], False))

    def testMultipartMixed(self):
        self.TestExtraction("""
multipart/mixed
    text/plain
    application/pdf""",
                  ('foo\n',
                   [('foo.pdf', 'application/pdf', b'foo\n')], False))

    def testMultipartMixedHtml(self):
        # test with html conversion enabled
        self.TestExtraction("""
multipart/mixed
    text/html
    application/pdf""",
                  ('bar >\n',
                   [('bar.html', 'text/html',
                      '<html><body>bar &gt;</body></html>\n'),
                   ('foo.pdf', 'application/pdf', b'foo\n')], False),
                            convert_html_with='dehtml')

        # test with html conversion disabled
        self.TestExtraction("""
multipart/mixed
    text/html
    application/pdf""",
                  (None,
                   [('bar.html', 'text/html',
                      '<html><body>bar &gt;</body></html>\n'),
                    ('foo.pdf', 'application/pdf', b'foo\n')], False),
                            convert_html_with=False)

    def testMultipartAlternative(self):
        self.TestExtraction("""
multipart/alternative
    text/plain
    application/pdf
        """, ('foo\n', [('foo.pdf', 'application/pdf', b'foo\n')], False))

    def testMultipartAlternativeHtml(self):
        self.TestExtraction("""
multipart/alternative
    text/html
    application/pdf""",
                  ('bar >\n',
                   [('bar.html', 'text/html',
                      '<html><body>bar &gt;</body></html>\n'),
                   ('foo.pdf', 'application/pdf', b'foo\n')], False),
                            convert_html_with='dehtml')

        self.TestExtraction("""
multipart/alternative
    text/html
    application/pdf""",
                  (None,
                   [('bar.html', 'text/html',
                      '<html><body>bar &gt;</body></html>\n'),
                    ('foo.pdf', 'application/pdf', b'foo\n')], False),
                            convert_html_with=False)

    def testMultipartAlternativeHtmlText(self):
        # text should take priority over html when html is first
        self.TestExtraction("""
multipart/alternative
    text/html
    text/plain
    application/pdf""",
                  ('foo\n',
                   [('bar.html', 'text/html',
                      '<html><body>bar &gt;</body></html>\n'),
                    ('foo.pdf', 'application/pdf', b'foo\n')], False),
                            convert_html_with='dehtml')

        # text should take priority over html when text is first
        self.TestExtraction("""
multipart/alternative
    text/plain
    text/html
    application/pdf""",
                  ('foo\n',
                   [('bar.html', 'text/html',
                      '<html><body>bar &gt;</body></html>\n'),
                    ('foo.pdf', 'application/pdf', b'foo\n')], False),
                            convert_html_with='dehtml')

        # text should take priority over html when text is second and
        # html is disabled
        self.TestExtraction("""
multipart/alternative
    text/html
    text/plain
    application/pdf""",
                  ('foo\n',
                   [('bar.html', 'text/html',
                      '<html><body>bar &gt;</body></html>\n'),
                    ('foo.pdf', 'application/pdf', b'foo\n')], False),
                            convert_html_with=False)

        # text should take priority over html when text is first and
        # html is disabled
        self.TestExtraction("""
multipart/alternative
    text/plain
    text/html
    application/pdf""",
                  ('foo\n',
                   [('bar.html', 'text/html',
                      '<html><body>bar &gt;</body></html>\n'),
                    ('foo.pdf', 'application/pdf', b'foo\n')], False),
                            convert_html_with=False)

    def testDeepMultipartAlternative(self):
        self.TestExtraction("""
multipart/mixed
    multipart/alternative
        text/plain
        application/pdf
        """, ('foo\n', [('foo.pdf', 'application/pdf', b'foo\n')], False))

    def testSignedText(self):
        self.TestExtraction("""
multipart/signed
    text/plain
    application/pgp-signature""", ('foo\n', [], False))

    def testSignedAttachments(self):
        self.TestExtraction("""
multipart/signed
    multipart/mixed
        text/plain
        application/pdf
    application/pgp-signature""",
                  ('foo\n',
                   [('foo.pdf', 'application/pdf', b'foo\n')], False))

    def testAttachedSignature(self):
        self.TestExtraction("""
multipart/mixed
    text/plain
    application/pgp-signature""",
                  ('foo\n',
                   [('foo.gpg', 'application/pgp-signature', b'foo\n')], False))

    def testMessageRfc822(self):
        self.TestExtraction("""
multipart/mixed
    message/rfc822""",
                  (None,
                   [('foo.eml', 'message/rfc822', 'Subject: foo\n\nfoo\n')], False))

# vim: set filetype=python ts=4 sw=4 et si
