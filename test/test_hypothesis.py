import unittest

import pytest

pytest.importorskip("hypothesis")

# ruff: noqa: E402
from hypothesis import example, given, settings
from hypothesis.strategies import binary, none, one_of, sampled_from, text

from roundup.anypy.strings import b2s, s2b, s2u, u2s
# ruff: noqa: I001  - yes I know I am using \ to continue the line...
from roundup.password import PasswordValueError, encodePassword, \
     h64decode, h64encode
from roundup.password import crypt as crypt_method

def Identity(x):
    return x


_max_examples = 1000


class HypoTestStrings(unittest.TestCase):

    @given(text())
    @settings(max_examples=_max_examples)
    def test_b2s(self, utf8_bytes):
        self.assertEqual(b2s(utf8_bytes.encode("utf-8")), utf8_bytes)

    @given(text())
    @settings(max_examples=_max_examples)
    def test_s2b(self, s):
        self.assertTrue(isinstance(s2b(s), bytes))

    @given(text())
    @settings(max_examples=_max_examples)
    @example("\U0001F600 hi there")  # smiley face emoji
    def test_s2u_u2s_invertable(self, s):
        self.assertEqual(u2s(s2u(s)), s)


class HypoTestPassword(unittest.TestCase):

    @given(binary())
    @example(b"")
    @settings(max_examples=_max_examples)
    def test_h64encode_h64decode(self, s):

        self.assertEqual(h64decode(h64encode(s)), s)

    crypt_modes = ["PBKDF2S5", "PBKDF2", "SSHA", "SHA", "MD5",
                   "plaintext", "zot"]
    if crypt_method:
        crypt_modes.append("crypt")

    @given(one_of(none(), text()),
           sampled_from(crypt_modes))
    @example("asd\x00df", "crypt")
    @settings(max_examples=_max_examples)  # deadline=None for debugging
    def test_encodePassword(self, password, scheme):

        if scheme == "crypt" and password and "\x00" in password:
            with self.assertRaises(ValueError) as e:
                encodePassword(password, scheme)
            if crypt_method:
                self.assertEqual(e.exception.args[0],
                                 "embedded null character")
            else:
                self.assertEqual(e.exception.args[0],
                                 "Unsupported encryption scheme 'crypt'")
        elif scheme == "plaintext":
            if password is not None:
                self.assertEqual(encodePassword(password, scheme), password)
            else:
                self.assertEqual(encodePassword(password, scheme), "")
        elif scheme == "zot":
            with self.assertRaises(PasswordValueError) as e:
                encodePassword(password, scheme)
            self.assertEqual(e.exception.args[0],
                             "Unknown encryption scheme 'zot'")
        else:
            # it shouldn't throw anything.
            pw = encodePassword(password, scheme)

            # verify format
            if scheme in ["PBKDF2S5", "PBKDF2"]:
                # 1000$XbSsijELEQbZZb1LlD7CFuotF/8$DdtssSlm.e
                self.assertRegex(pw, r"^\d{4,8}\$.{27}\$.*")
            elif scheme == "SSHA":
                # vqDbjvs8rhrS1AJxHYEGGXQW3x7STAPgo7uCtnw4GYgU7FN5VYbZxccQYCC0eXOxSipLbtgBudH1vDRMNlG0uw==
                self.assertRegex(pw, r"^[^=]*={0,3}$")
            elif scheme == "SHA":
                # da39a3ee5e6b4b0d3255bfef95601890afd80709'
                self.assertRegex(pw, r"^[a-z0-9]{40}$")
            elif scheme == "MD5":
                # d41d8cd98f00b204e9800998ecf8427e'
                self.assertRegex(pw, r"^[a-z0-9]{32}$")
            elif scheme == "crypt":
                # crypt_method is None if crypt is unknown
                if crypt_method:
                    # WqzFDzhi8MmoU
                    self.assertRegex(pw, r"^[A-Za-z0-9./]{13}$")
            else:
                self.assertFalse("Unknown scheme: %s, val: %s" % (scheme, pw))
