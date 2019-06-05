# -*- coding: utf-8 -*-
import email
import textwrap
from unittest import TestCase

from roundup.mailgw import RoundupMessage

PART_TYPES = {
    'multipart/signed': '    boundary="boundary-{indent}";\n',
    'multipart/mixed': '    boundary="boundary-{indent}";\n',
    'multipart/alternative': '    boundary="boundary-{indent}";\n',
    'text/plain': '    name="foo.txt"\n\nfoo\n',
    'text/plain_2': '    name="foo2.txt"\n\nfoo2\n',
    'text/plain_3': '    name="foo3.txt"\n\nfoo3\n',
    'text/html': '    name="foo.html"\n\n<html>foo</html>\n',
    'application/pgp-signature': '    name="foo.gpg"\nfoo\n',
    'application/pdf': '    name="foo.pdf"\nfoo\n',
    'application/pdf_2': '    name="foo2.pdf"\nfoo2\n',
    'message/rfc822': '\nSubject: foo\n\nfoo\n',
}


def message_from_string(msg):
    return email.message_from_string(
        textwrap.dedent(msg).lstrip(),
        RoundupMessage)


def construct_message(spec, depth=0):
    parts = []
    for content_type in spec:
        if isinstance(content_type, list):
            parts.extend(construct_message(content_type, depth=(depth + 1)))
            parts.append('\n--boundary-{0}--\n'.format(depth + 1))
        else:
            if depth > 0:
                parts.append('\n--boundary-{0}\n'.format(depth))

            parts.append(
                'Content-Type: {0};\n'.format(content_type.split('_')[0]))
            parts.append(PART_TYPES[content_type].format(indent=(depth + 1)))

    if depth == 0:
        return email.message_from_string(''.join(parts), RoundupMessage)
    else:
        return parts


class FlattenRoundupMessageTests(TestCase):
    def test_flatten_with_from(self):
        msg_string = textwrap.dedent("""
            From: Some User <some.user@example.com>
            To: issue_tracker@example.com
            Message-Id: <dummy_test_message_id>
            Subject: Test line start with from

            From here to there!
        """).lstrip()

        msg = email.message_from_string(msg_string, RoundupMessage)
        self.assertEqual(msg.flatten(), msg_string)


class HeaderRoundupMessageTests(TestCase):
    msg = message_from_string("""
        Content-Type: text/plain;
            charset="iso-8859-1"
        From: =?utf8?b?SOKCrGxsbw==?= <hello@example.com>
        To: Issue Tracker <issue_tracker@example.com>
        Cc: =?utf8?b?SOKCrGxsbw==?= <hello@example.com>,
            Some User <some.user@example.com>
        Message-Id: <dummy_test_message_id>
        Subject: [issue] Testing...

        This is a test submission of a new issue.
    """)

    # From line has a null/empty encoding spec
    # to trigger failure in mailgw.py:RoundupMessage::_decode_header
    bad_msg_utf8 = message_from_string("""
        Content-Type: text/plain;
            charset="iso-8859-1"
        From: =??b?SOKCrGxsbw=====?= <hello@example.com>
        To: Issue Tracker <issue_tracker@example.com>
        Cc: =?utf8?b?SOKCrGxsbw==?= <hello@example.com>,
            Some User <some.user@example.com>
        Message-Id: <dummy_test_message_id>
        Subject: [issue] Testing...

        This is a test submission of a new issue.
    """)

    bad_msg_iso_8859_1 = message_from_string("""
        Content-Type: text/plain;
            charset="iso-8859-1"
        From: =??q?\x80SOKCrGxsbw=====?= <hello@example.com>
        To: Issue Tracker <issue_tracker@example.com>
        Cc: =?utf8?b?SOKCrGxsbw==?= <hello@example.com>,
            Some User <some.user@example.com>
        Message-Id: <dummy_test_message_id>
        Subject: [issue] Testing...

        This is a test submission of a new issue.
    """)

    def test_get_plain_header(self):
        self.assertEqual(
            self.msg.get_header('to'),
            'Issue Tracker <issue_tracker@example.com>')

    def test_get_encoded_header(self):
        self.assertEqual(
            self.msg.get_header('from'),
            'H€llo <hello@example.com>')

        # issue2551008 null encoding causes crash.
        self.assertEqual(
            self.bad_msg_utf8.get_header('from'),
            'H€llo <hello@example.com>')

        # the decoded value is not what the user wanted,
        # but they should have created a valid header
        # if they wanted the right outcome...
        self.assertIn(
            self.bad_msg_iso_8859_1.get_header('from'),
            (
                '\xc2\x80SOKCrGxsbw===== <hello@example.com>', # python 2
                '\x80SOKCrGxsbw===== <hello@example.com>'      # python 3
            ))

    def test_get_address_list(self):
        self.assertEqual(self.msg.get_address_list('cc'), [
            ('H€llo', 'hello@example.com'),
            ('Some User', 'some.user@example.com'),
        ])


class BodyRoundupMessageTests(TestCase):
    def test_get_body_iso_8859_1(self):
        msg = message_from_string("""
            Content-Type: text/plain; charset="iso-8859-1"
            Content-Transfer-Encoding: quoted-printable

            A message with encoding (encoded oe =F6)
        """)

        self.assertEqual(
            msg.get_body(),
            'A message with encoding (encoded oe ö)\n')

    def test_get_body_utf_8(self):
        msg = message_from_string("""
            Content-Type: text/plain; charset="utf-8"
            Content-Transfer-Encoding: quoted-printable

            A message with encoding (encoded oe =C3=B6)
        """)

        self.assertEqual(
            msg.get_body(),
            'A message with encoding (encoded oe ö)\n')

    def test_get_body_base64(self):
        msg = message_from_string("""
            Content-Type: application/octet-stream
            Content-Disposition: attachment; filename="message.dat"
            Content-Transfer-Encoding: base64

            dGVzdCBlbmNvZGVkIG1lc3NhZ2U=
        """)

        self.assertEqual(msg.get_body(), b'test encoded message')


class AsAttachmentRoundupMessageTests(TestCase):
    def test_text_plain(self):
        msg = message_from_string("""
            Content-Type: text/plain; charset="iso-8859-1

            Plain text message
        """)

        self.assertEqual(
            msg.as_attachment(),
            (None, 'text/plain', 'Plain text message\n'))

    def test_octet_stream(self):
        msg = message_from_string("""
            Content-Type: application/octet-stream
            Content-Disposition: attachment; filename="message.dat"
            Content-Transfer-Encoding: base64

            dGVzdCBlbmNvZGVkIG1lc3NhZ2U=
        """)

        self.assertEqual(
            msg.as_attachment(),
            ('message.dat', 'application/octet-stream',
             b'test encoded message'))

    def test_rfc822(self):
        msg = message_from_string("""
            Content-Type: message/rfc822

            Subject: foo

            foo
        """)

        self.assertEqual(
            msg.as_attachment(),
            ('foo.eml', 'message/rfc822', 'Subject: foo\n\nfoo\n'))

    def test_rfc822_no_subject(self):
        msg = message_from_string("""
            Content-Type: message/rfc822

            X-No-Headers: nope

            foo
        """)

        self.assertEqual(
            msg.as_attachment(),
            (None, 'message/rfc822', 'X-No-Headers: nope\n\nfoo\n'))

    def test_rfc822_no_payload(self):
        msg = message_from_string("""\
            Content-Type: message/rfc822
        """)

        self.assertEqual(
            msg.as_attachment(),
            (None, 'message/rfc822', '\n'))


class ExtractContentRoundupMessageTests(TestCase):
    def test_text_plain(self):
        msg = construct_message(['text/plain'])

        self.assertEqual(msg.extract_content(), ('foo\n', [], False))

    def test_attached_text_plain(self):
        msg = construct_message([
            'multipart/mixed', [
                'text/plain',
                'text/plain',
            ],
        ])

        self.assertEqual(msg.extract_content(), (
            'foo\n',
            [('foo.txt', 'text/plain', 'foo\n')],
            False
        ))

    def test_multipart_mixed(self):
        msg = construct_message([
            'multipart/mixed', [
                'text/plain',
                'application/pdf',
            ],
        ])

        self.assertEqual(msg.extract_content(), (
            'foo\n',
            [('foo.pdf', 'application/pdf', b'foo\n')],
            False
        ))

    def test_multipart_alternative(self):
        msg = construct_message([
            'multipart/alternative', [
                'text/plain',
                'text/html',
            ],
        ])

        self.assertEqual(msg.extract_content(), (
            'foo\n',
            [('foo.html', 'text/html', '<html>foo</html>\n')],
            False
        ))

    def test_deep_multipart_alternative(self):
        msg = construct_message([
            'multipart/mixed', [
                'multipart/alternative', [
                    'text/plain',
                    'application/pdf',
                    'text/plain_2',
                    'text/html',
                ],
                'multipart/alternative', [
                    'text/plain_3',
                    'application/pdf_2',
                ],
            ],
        ])

        self.assertEqual(msg.extract_content(), (
            'foo2\n', [
                ('foo.pdf', 'application/pdf', b'foo\n'),
                ('foo.txt', 'text/plain', 'foo\n'),
                ('foo.html', 'text/html', '<html>foo</html>\n'),
                ('foo3.txt', 'text/plain', 'foo3\n'),
                ('foo2.pdf', 'application/pdf', b'foo2\n'),
            ],
            False
        ))

    def test_deep_multipart_alternative_ignore(self):
        msg = construct_message([
            'multipart/mixed', [
                'multipart/alternative', [
                    'text/plain',
                    'application/pdf',
                    'text/plain_2',
                    'text/html',
                ],
                'multipart/alternative', [
                    'text/plain_3',
                    'application/pdf_2',
                ],
            ],
        ])

        msg.extract_content(ignore_alternatives=True)
        self.assertEqual(msg.extract_content(ignore_alternatives=True), (
            'foo2\n', [
                ('foo3.txt', 'text/plain', 'foo3\n'),
                ('foo2.pdf', 'application/pdf', b'foo2\n'),
            ],
            False
        ))

    def test_signed_text(self):
        msg = construct_message([
            'multipart/signed', [
                'text/plain',
                'application/pgp-signature',
            ],
        ])

        self.assertEqual(msg.extract_content(), ('foo\n', [], False))

    def test_signed_attachemts(self):
        msg = construct_message([
            'multipart/signed', [
                'multipart/mixed', [
                    'text/plain',
                    'application/pdf',
                ],
                'application/pgp-signature',
            ],
        ])

        self.assertEqual(msg.extract_content(), (
            'foo\n',
            [('foo.pdf', 'application/pdf', b'foo\n')],
            False
        ))

    def test_attached_signature(self):
        msg = construct_message([
            'multipart/mixed', [
                'text/plain',
                'application/pgp-signature',
            ],
        ])

        self.assertEqual(msg.extract_content(), (
            'foo\n',
            [('foo.gpg', 'application/pgp-signature', b'foo\n')],
            False
        ))

    def test_rfc822_message(self):
        msg = construct_message([
            'multipart/mixed', [
                'message/rfc822',
            ],
        ])

        self.assertEqual(msg.extract_content(), (
            None,
            [('foo.eml', 'message/rfc822', 'Subject: foo\n\nfoo\n')],
            False
        ))

    def test_rfc822_message_unpack(self):
        msg = construct_message([
            'multipart/mixed', [
                'text/plain',
                'message/rfc822',
            ],
        ])

        self.assertEqual(msg.extract_content(unpack_rfc822=True), (
            'foo\n',
            [(None, 'text/plain', 'foo\n')],
            False
        ))


class PgpDetectRoundupMessageTests(TestCase):
    def test_pgp_message_signed(self):
        msg = message_from_string("""
            Content-Type: multipart/signed; micalg=pgp-sha1;
                    protocol="application/pgp-signature"

            Fake Body
        """)

        self.assertTrue(msg.pgp_signed())

    def test_pgp_message_not_signed(self):
        msg = message_from_string("""
            Content-Type: text/plain

            Fake Body
        """)

        self.assertFalse(msg.pgp_signed())

    def test_pgp_message_signed_protocol_missing(self):
        msg = message_from_string("""
            Content-Type: multipart/signed; micalg=pgp-sha1

            Fake Body
        """)

        self.assertFalse(msg.pgp_signed())

    def test_pgp_message_signed_protocol_invalid(self):
        msg = message_from_string("""
            Content-Type: multipart/signed;
                protocol="application/not-pgp-signature"

            Fake Body
        """)

        self.assertFalse(msg.pgp_signed())

    def test_pgp_message_encrypted(self):
        msg = message_from_string("""
            Content-Type: multipart/encrypted;
                protocol="application/pgp-encrypted"

            Fake Body
        """)

        self.assertTrue(msg.pgp_encrypted())

    def test_pgp_message_not_encrypted(self):
        msg = message_from_string("""
            Content-Type: text/plain

            Fake Body
        """)

        self.assertFalse(msg.pgp_encrypted())

    def test_pgp_message_encrypted_protocol_missing(self):
        msg = message_from_string("""
            Content-Type: multipart/encrypted

            Fake Body
        """)

        self.assertFalse(msg.pgp_encrypted())

    def test_pgp_message_encrypted_protocol_invalid(self):
        msg = message_from_string("""
            Content-Type: multipart/encrypted;
                protocol="application/not-pgp-encrypted"

            Fake Body
        """)

        self.assertFalse(msg.pgp_encrypted())

# TODO: testing of the verify_signature() and decrypt() RoundupMessage methods.
#   The whole PGP testing stuff seems a bit messy, so we will rely on the tests
#   in test_mailgw for the time being
