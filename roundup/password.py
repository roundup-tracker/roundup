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
"""Password handling (encoding, decoding).
"""
__docformat__ = 'restructuredtext'

import os
import re
import string
import sys
import warnings
from base64 import b64decode, b64encode
from hashlib import md5, sha1, sha512

from roundup.anypy import random_
from roundup.anypy.strings import b2s, s2b, us2s
from roundup.exceptions import RoundupException

try:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        import crypt
except ImportError:
    crypt = None

_bempty = b""
_bjoin = _bempty.join


class ConfigNotSet(RoundupException):
    pass


def bchr(c):
    if bytes is str:
        # Python 2.
        return chr(c)
    else:
        # Python 3.
        return bytes((c,))


def bord(c):
    if bytes is str:
        # Python 2.
        return ord(c)
    else:
        # Python 3.  Elements of bytes are integers.
        return c


# NOTE: PBKDF2 hash is using this variant of base64 to minimize encoding size,
#      and have charset that's compatible w/ unix crypt variants
def h64encode(data):
    """encode using variant of base64"""
    return b2s(b64encode(data, b"./").strip(b"=\n"))


def h64decode(data):
    """decode using variant of base64"""
    data = s2b(data)
    off = len(data) % 4
    if off == 0:
        return b64decode(data, b"./")
    elif off == 1:
        raise ValueError("Invalid base64 input")
    elif off == 2:
        return b64decode(data + b"==", b"./")
    else:
        return b64decode(data + b"=", b"./")


try:
    from hashlib import pbkdf2_hmac

    def _pbkdf2(password, salt, rounds, keylen):
        return pbkdf2_hmac('sha1', password, salt, rounds, keylen)

    def _pbkdf2_sha512(password, salt, rounds, keylen):
        return pbkdf2_hmac('sha512', password, salt, rounds, keylen)
except ImportError:
    # no hashlib.pbkdf2_hmac - make our own pbkdf2 function
    from hmac import HMAC
    from struct import pack

    def xor_bytes(left, right):
        "perform bitwise-xor of two byte-strings"
        return _bjoin(bchr(bord(l) ^ bord(r))
                      for l, r in zip(left, right))  # noqa: E741

    def _pbkdf2(password, salt, rounds, keylen, sha=sha1):
        if sha not in [sha1, sha512]:
            raise ValueError(
                "Invalid sha value passed to _pbkdf2: %s" % sha)
        if sha == sha512:
            digest_size = 64  # sha512 generates 64-byte blocks.
        else:
            digest_size = 20  # sha1 generates 20-byte blocks

        total_blocks = int((keylen + digest_size - 1) / digest_size)
        hmac_template = HMAC(password, None, sha)
        out = _bempty
        for i in range(1, total_blocks + 1):
            hmac = hmac_template.copy()
            hmac.update(salt + pack(">L", i))
            block = tmp = hmac.digest()
            for _j in range(rounds - 1):
                hmac = hmac_template.copy()
                hmac.update(tmp)
                tmp = hmac.digest()
                # TODO: need to speed up this call
                block = xor_bytes(block, tmp)
            out += block
        return out[:keylen]

    def _pbkdf2_sha512(password, salt, rounds, keylen):
        return _pbkdf2(password, salt, rounds, keylen, sha=sha512)


def ssha(password, salt):
    ''' Make ssha digest from password and salt.
    Based on code of Roberto Aguilar <roberto@baremetal.io>
    https://gist.github.com/rca/7217540
    '''
    shaval = sha1(password)  # noqa: S324
    shaval.update(salt)
    ssha_digest = b2s(b64encode(shaval.digest() + salt).strip())
    return ssha_digest


def pbkdf2_sha512(password, salt, rounds, keylen):
    """PBKDF2-HMAC-SHA512 password-based key derivation

    :arg password: passphrase to use to generate key (if unicode,
     converted to utf-8)
    :arg salt: salt bytes to use when generating key
    :param rounds: number of rounds to use to generate key
    :arg keylen: number of bytes to generate

    If hashlib supports pbkdf2, uses it's implementation as backend.

    Unlike pbkdf2, this uses sha512 not sha1 as it's hash.

    :returns:
        raw bytes of generated key
    """
    password = s2b(us2s(password))
    if keylen > 64:
        # This statement may be old. - not seeing issues in testing
        # with keylen > 40.
        #
        # NOTE: pbkdf2 allows up to (2**31-1)*20 bytes,
        # but m2crypto has issues on some platforms above 40,
        # and such sizes aren't needed for a password hash anyways...
        raise ValueError("key length too large")
    if rounds < 1:
        raise ValueError("rounds must be positive number")
    return _pbkdf2_sha512(password, salt, rounds, keylen)


def pbkdf2(password, salt, rounds, keylen):
    """pkcs#5 password-based key derivation v2.0

    :arg password: passphrase to use to generate key (if unicode,
     converted to utf-8)
    :arg salt: salt bytes to use when generating key
    :param rounds: number of rounds to use to generate key
    :arg keylen: number of bytes to generate

    If hashlib supports pbkdf2, uses it's implementation as backend.

    :returns:
        raw bytes of generated key
    """
    password = s2b(us2s(password))
    if keylen > 40:
        # NOTE: pbkdf2 allows up to (2**31-1)*20 bytes,
        # but m2crypto has issues on some platforms above 40,
        # and such sizes aren't needed for a password hash anyways...
        raise ValueError("key length too large")
    if rounds < 1:
        raise ValueError("rounds must be positive number")
    return _pbkdf2(password, salt, rounds, keylen)


class PasswordValueError(ValueError):
    """ The password value is not valid """
    pass


def pbkdf2_unpack(pbkdf2):
    """ unpack pbkdf2 encrypted password into parts,
        assume it has format "{rounds}${salt}${digest}
    """
    pbkdf2 = us2s(pbkdf2)
    try:
        rounds, salt, digest = pbkdf2.split("$")
    except ValueError:
        raise PasswordValueError("invalid PBKDF2 hash (wrong number of "
                                 "separators)")
    if rounds.startswith("0"):
        raise PasswordValueError("invalid PBKDF2 hash (zero-padded rounds)")
    try:
        rounds = int(rounds)
    except ValueError:
        raise PasswordValueError("invalid PBKDF2 hash (invalid rounds)")
    raw_salt = h64decode(salt)
    return rounds, salt, raw_salt, digest


def encodePassword(plaintext, scheme, other=None, config=None):
    """Encrypt the plaintext password.
    """
    if plaintext is None:
        plaintext = ""
    if scheme in ["PBKDF2", "PBKDF2S5"]:  # all PBKDF schemes
        if other:
            rounds, salt, raw_salt, _digest = pbkdf2_unpack(other)
        else:
            raw_salt = random_.token_bytes(20)
            salt = h64encode(raw_salt)
            if config:
                rounds = config.PASSWORD_PBKDF2_DEFAULT_ROUNDS

                # if we are testing
                if ("pytest" in sys.modules and
                    "PYTEST_CURRENT_TEST" in os.environ):
                    if ("PYTEST_USE_CONFIG" in os.environ):
                        rounds = config.PASSWORD_PBKDF2_DEFAULT_ROUNDS
                    else:
                        # Use 1000 rounds unless the test signals it
                        # wants the config number by setting
                        # PYTEST_USE_CONFIG. Using the production
                        # rounds value of 2,000,000 (for sha1) makes
                        # testing increase from 12 minutes to 1 hour in CI.
                        rounds = 1000
            elif ("pytest" in sys.modules and
                  "PYTEST_CURRENT_TEST" in os.environ):
                # Set rounds to 1000 if no config is passed and
                # we are running within a pytest test.
                rounds = 1000
            else:
                import logging
                # Log and abort.  Initialize rounds and log (which
                # will probably be ignored) with traceback in case
                # ConfigNotSet exception is removed in the
                # future.
                rounds = 2000000
                logger = logging.getLogger('roundup')
                if sys.version_info[0] > 2:
                    logger.critical(
                        "encodePassword called without config.",
                        stack_info=True)
                else:
                    import inspect
                    import traceback

                    where = inspect.currentframe()
                    trace = traceback.format_stack(where)
                    logger.critical(
                        "encodePassword called without config. %s",
                        trace[:-1]
                    )
                raise ConfigNotSet("encodePassword called without config.")

        if rounds < 1000:
            raise PasswordValueError("invalid PBKDF2 hash (rounds too low)")
        if scheme == "PBKDF2S5":
            raw_digest = pbkdf2_sha512(plaintext, raw_salt, rounds, 64)
        else:
            raw_digest = pbkdf2(plaintext, raw_salt, rounds, 20)
        return "%d$%s$%s" % (rounds, salt, h64encode(raw_digest))
    elif scheme == 'SSHA':
        if other:
            raw_other = b64decode(other)
            salt = raw_other[20:]
        else:
            # new password
            # variable salt length
            salt_len = random_.randbelow(52 - 36) + 36
            salt = random_.token_bytes(salt_len)
        s = ssha(s2b(plaintext), salt)
    elif scheme == 'SHA':
        s = sha1(s2b(plaintext)).hexdigest()  # noqa: S324
    elif scheme == 'MD5':
        s = md5(s2b(plaintext)).hexdigest()   # noqa: S324
    elif scheme == 'crypt':
        if crypt is None:
            raise PasswordValueError(
                'Unsupported encryption scheme %r' % scheme)
        if other is not None:
            salt = other
        else:
            saltchars = './0123456789' + string.ascii_letters
            salt = random_.choice(saltchars) + random_.choice(saltchars)
        s = crypt.crypt(plaintext, salt)
    elif scheme == 'plaintext':
        s = plaintext
    else:
        raise PasswordValueError('Unknown encryption scheme %r' % scheme)
    return s


def generatePassword(length=12):
    chars = string.ascii_letters + string.digits
    password = [random_.choice(chars) for x in range(length - 1)]
    # make sure there is at least one digit
    digitidx = random_.randbelow(length)
    password[digitidx:digitidx] = [random_.choice(string.digits)]
    return ''.join(password)


class JournalPassword:
    """ Password dummy instance intended for journal operation.
        We do not store passwords in the journal any longer.  The dummy
        version only reads the encryption scheme from the given
        encrypted password.
    """
    default_scheme = 'PBKDF2'        # new encryptions use this scheme
    pwre = re.compile(r'{(\w+)}(.+)')

    def __init__(self, encrypted=''):
        if isinstance(encrypted, self.__class__):
            self.scheme = encrypted.scheme or self.default_scheme
        else:
            m = self.pwre.match(encrypted)
            if m:
                self.scheme = m.group(1)
            else:
                self.scheme = self.default_scheme
        self.password = ''

    def dummystr(self):
        """ return dummy string to store in journal
            - reports scheme, but nothing else
        """
        return "{%s}*encrypted*" % (self.scheme,)

    __str__ = dummystr

    def __eq__(self, other):
        """Compare this password against another password."""
        # check to see if we're comparing instances
        if isinstance(other, self.__class__):
            if self.scheme != other.scheme:
                return False
            return self.password == other.password

        # assume password is plaintext
        if self.password is None:
            raise ValueError('Password not set')
        return self.password == encodePassword(other, self.scheme,
                                               self.password or None)

    def __ne__(self, other):
        return not self.__eq__(other)


class Password(JournalPassword):
    """The class encapsulates a Password property type value in the database.

    The encoding of the password is one if None, 'SHA', 'MD5' or 'plaintext'.
    The encodePassword function is used to actually encode the password from
    plaintext. The None encoding is used in legacy databases where no
    encoding scheme is identified.

    The scheme is stored with the encoded data in the database:
        {scheme}data

    Example usage:
    >>> p = Password('sekrit')
    >>> p == 'sekrit'
    1
    >>> p != 'not sekrit'
    1
    >>> 'sekrit' == p
    1
    >>> 'not sekrit' != p
    1
    """

    deprecated_schemes = ["SSHA", "SHA", "MD5", "plaintext"]
    if crypt:
        # place just before plaintext if crypt is available
        deprecated_schemes.insert(-1, "crypt")
    experimental_schemes = ["PBKDF2S5"]
    known_schemes = ["PBKDF2"] + experimental_schemes + \
        deprecated_schemes

    def __init__(self, plaintext=None, scheme=None, encrypted=None,
                 strict=False, config=None):
        """Call setPassword if plaintext is not None."""
        if scheme is None:
            scheme = self.default_scheme
        if plaintext is not None:
            self.setPassword(plaintext, scheme, config=config)
        elif encrypted is not None:
            self.unpack(encrypted, scheme, strict=strict, config=config)
        else:
            self.scheme = self.default_scheme
            self.password = None
            self.plaintext = None

    def __repr__(self):
        return self.__str__()

    def needs_migration(self, config):
        """ Password has insecure scheme or other insecure parameters
            and needs migration to new password scheme
        """
        if self.scheme in self.deprecated_schemes:
            return True

        rounds, _salt, _raw_salt, _digest = pbkdf2_unpack(self.password)

        if rounds < 1000:
            return True

        if (self.scheme == "PBKDF2"):
            new_rounds = config.PASSWORD_PBKDF2_DEFAULT_ROUNDS
            if ("pytest" in sys.modules and
                "PYTEST_CURRENT_TEST" in os.environ):
                if ("PYTEST_USE_CONFIG" in os.environ):
                    new_rounds = config.PASSWORD_PBKDF2_DEFAULT_ROUNDS
                else:
                    # for testing
                    new_rounds = 1000
            if rounds < int(new_rounds):
                return True
        return False

    def unpack(self, encrypted, scheme=None, strict=False, config=None):
        """Set the password info from the scheme:<encrypted info> string
           (the inverse of __str__)
        """
        m = self.pwre.match(encrypted)
        if m:
            self.scheme = m.group(1)
            self.password = m.group(2)
            self.plaintext = None
        else:
            # currently plaintext - encrypt
            self.setPassword(encrypted, scheme, config=config)
        if strict and self.scheme not in self.known_schemes:
            raise PasswordValueError("Unknown encryption scheme: %r" %
                                     (self.scheme,))

    def setPassword(self, plaintext, scheme=None, config=None):
        """Sets encrypts plaintext."""
        if scheme is None:
            scheme = self.default_scheme
        self.scheme = scheme
        self.password = encodePassword(plaintext, scheme, config=config)
        self.plaintext = plaintext

    def __str__(self):
        """Stringify the encrypted password for database storage."""
        if self.password is None:
            raise ValueError('Password not set')
        return '{%s}%s' % (self.scheme, self.password)


def test_missing_crypt(config=None):
    _p = encodePassword('sekrit', 'crypt', config=config)


def test(config=None):
    # ruff: noqa: S101 SIM300 - asserts are ok
    # SHA
    p = Password('sekrit', config=config)
    assert Password(encrypted=str(p)) == 'sekrit'
    assert 'sekrit' == Password(encrypted=str(p))
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

    # MD5
    p = Password('sekrit', 'MD5', config=config)
    assert Password(encrypted=str(p)) == 'sekrit'
    assert 'sekrit' == Password(encrypted=str(p))
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

    # crypt
    if crypt:  # not available on Windows
        p = Password('sekrit', 'crypt', config=config)
        assert Password(encrypted=str(p)) == 'sekrit'
        assert 'sekrit' == Password(encrypted=str(p))
        assert p == 'sekrit'
        assert p != 'not sekrit'
        assert 'sekrit' == p
        assert 'not sekrit' != p

    # SSHA
    p = Password('sekrit', 'SSHA', config=config)
    assert Password(encrypted=str(p)) == 'sekrit'
    assert 'sekrit' == Password(encrypted=str(p))
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

    # PBKDF2 - low level function
    from binascii import unhexlify
    k = pbkdf2("password", b"ATHENA.MIT.EDUraeburn", 1200, 32)
    assert k == unhexlify("5c08eb61fdf71e4e4ec3cf6ba1f5512ba7e52ddbc5e5142f708a31e2e62b1e13")

    # PBKDF2 - hash function
    h = "5000$7BvbBq.EZzz/O0HuwX3iP.nAG3s$g3oPnFFaga2BJaX5PoPRljl4XIE"
    assert encodePassword("sekrit", "PBKDF2", h, config=config) == h

    # PBKDF2 - high level integration
    p = Password('sekrit', 'PBKDF2', config=config)
    assert Password(encrypted=str(p)) == 'sekrit'
    assert 'sekrit' == Password(encrypted=str(p))
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

    # PBKDF2S5 - high level integration
    p = Password('sekrit', 'PBKDF2S5', config=config)
    print(p)
    assert Password(encrypted=str(p)) == 'sekrit'
    assert 'sekrit' == Password(encrypted=str(p))
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p


if __name__ == '__main__':
    # invoking this with:
    #  PYTHONPATH=. python2 roundup/password.py
    # or with python3, results in sys.path starting with:
    #   ['/path/to/./roundup',
    #    '/path/to/.',
    #    '/usr/lib/python2.7',
    # which makes import roundup.anypy.html fail in python2
    # when importing
    #    from cgi import escape as html_escape
    # because cgi is not /usr/lib/python2.7/cgi but
    # roundup/cgi. Modify the path to remove the bogus trailing /roundup

    sys.path[0] = sys.path[0][:sys.path[0].rindex('/')]

    # we continue with our regularly scheduled tests
    from roundup.configuration import CoreConfig
    test(CoreConfig())
    crypt = None
    exception = None
    try:
        test_missing_crypt(CoreConfig())
    except PasswordValueError as e:
        exception = e
    assert exception is not None
    assert exception.__str__() == "Unsupported encryption scheme 'crypt'"

# vim: set filetype=python sts=4 sw=4 et si :
