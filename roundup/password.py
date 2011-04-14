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
# $Id: password.py,v 1.15 2005-12-25 15:38:40 a1s Exp $

"""Password handling (encoding, decoding).
"""
__docformat__ = 'restructuredtext'

import re, string, random
from base64 import b64encode, b64decode
from roundup.anypy.hashlib_ import md5, sha1
try:
    import crypt
except ImportError:
    crypt = None

_bempty = ""
_bjoin = _bempty.join

def getrandbytes(count):
    return _bjoin(chr(random.randint(0,255)) for i in xrange(count))

#NOTE: PBKDF2 hash is using this variant of base64 to minimize encoding size,
#      and have charset that's compatible w/ unix crypt variants
def h64encode(data):
    """encode using variant of base64"""
    return b64encode(data, "./").strip("=\n")

def h64decode(data):
    """decode using variant of base64"""
    off = len(data) % 4
    if off == 0:
        return b64decode(data, "./")
    elif off == 1:
        raise ValueError("invalid bas64 input")
    elif off == 2:
        return b64decode(data + "==", "./")
    else:
        return b64decode(data + "=", "./")

try:
    from M2Crypto.EVP import pbkdf2 as _pbkdf2
except ImportError:
    #no m2crypto - make our own pbkdf2 function
    from struct import pack
    from hmac import HMAC
    try:
        from hashlib import sha1
    except ImportError:
        from sha import new as sha1

    def xor_bytes(left, right):
        "perform bitwise-xor of two byte-strings"
        return _bjoin(chr(ord(l) ^ ord(r)) for l, r in zip(left, right))

    def _pbkdf2(password, salt, rounds, keylen):
        digest_size = 20 # sha1 generates 20-byte blocks
        total_blocks = int((keylen+digest_size-1)/digest_size)
        hmac_template = HMAC(password, None, sha1)
        out = _bempty
        for i in xrange(1, total_blocks+1):
            hmac = hmac_template.copy()
            hmac.update(salt + pack(">L",i))
            block = tmp = hmac.digest()
            for j in xrange(rounds-1):
                hmac = hmac_template.copy()
                hmac.update(tmp)
                tmp = hmac.digest()
                #TODO: need to speed up this call
                block = xor_bytes(block, tmp)
            out += block
        return out[:keylen]

def pbkdf2(password, salt, rounds, keylen):
    """pkcs#5 password-based key derivation v2.0

    :arg password: passphrase to use to generate key (if unicode, converted to utf-8)
    :arg salt: salt string to use when generating key (if unicode, converted to utf-8)
    :param rounds: number of rounds to use to generate key
    :arg keylen: number of bytes to generate

    If M2Crypto is present, uses it's implementation as backend.

    :returns:
        raw bytes of generated key
    """
    if isinstance(password, unicode):
        password = password.encode("utf-8")
    if isinstance(salt, unicode):
        salt = salt.encode("utf-8")
    if keylen > 40:
        #NOTE: pbkdf2 allows up to (2**31-1)*20 bytes,
        # but m2crypto has issues on some platforms above 40,
        # and such sizes aren't needed for a password hash anyways...
        raise ValueError, "key length too large"
    if rounds < 1:
        raise ValueError, "rounds must be positive number"
    return _pbkdf2(password, salt, rounds, keylen)

class PasswordValueError(ValueError):
    """ The password value is not valid """
    pass

def encodePassword(plaintext, scheme, other=None):
    """Encrypt the plaintext password.
    """
    if plaintext is None:
        plaintext = ""
    if scheme == "PBKDF2":
        if other:
            #assume it has format "{rounds}${salt}${digest}"
            if isinstance(other, unicode):
                other = other.encode("ascii")
            try:
                rounds, salt, digest = other.split("$")
            except ValueError:
                raise PasswordValueError, "invalid PBKDF2 hash (wrong number of separators)"
            if rounds.startswith("0"):
                raise PasswordValueError, "invalid PBKDF2 hash (zero-padded rounds)"
            try:
                rounds = int(rounds)
            except ValueError:
                raise PasswordValueError, "invalid PBKDF2 hash (invalid rounds)"
            raw_salt = h64decode(salt)
        else:
            raw_salt = getrandbytes(20)
            salt = h64encode(raw_salt)
            #FIXME: find way to access config, so default rounds
            # can be altered for faster/slower hosts via config.ini
            rounds = 10000
        if rounds < 1000:
            raise PasswordValueError, "invalid PBKDF2 hash (rounds too low)"
        raw_digest = pbkdf2(plaintext, raw_salt, rounds, 20)
        return "%d$%s$%s" % (rounds, salt, h64encode(raw_digest))
    elif scheme == 'SHA':
        s = sha1(plaintext).hexdigest()
    elif scheme == 'MD5':
        s = md5(plaintext).hexdigest()
    elif scheme == 'crypt' and crypt is not None:
        if other is not None:
            salt = other
        else:
            saltchars = './0123456789'+string.letters
            salt = random.choice(saltchars) + random.choice(saltchars)
        s = crypt.crypt(plaintext, salt)
    elif scheme == 'plaintext':
        s = plaintext
    else:
        raise PasswordValueError, 'unknown encryption scheme %r'%scheme
    return s

def generatePassword(length=8):
    chars = string.letters+string.digits
    return ''.join([random.choice(chars) for x in range(length)])

class Password:
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
    #TODO: code to migrate from old password schemes.

    default_scheme = 'PBKDF2'        # new encryptions use this scheme
    known_schemes = [ "PBKDF2", "SHA", "MD5", "crypt", "plaintext" ]
    pwre = re.compile(r'{(\w+)}(.+)')

    def __init__(self, plaintext=None, scheme=None, encrypted=None, strict=False):
        """Call setPassword if plaintext is not None."""
        if scheme is None:
            scheme = self.default_scheme
        if plaintext is not None:
            self.setPassword (plaintext, scheme)
        elif encrypted is not None:
            self.unpack(encrypted, scheme, strict=strict)
        else:
            self.scheme = self.default_scheme
            self.password = None
            self.plaintext = None

    def unpack(self, encrypted, scheme=None, strict=False):
        """Set the password info from the scheme:<encryted info> string
           (the inverse of __str__)
        """
        m = self.pwre.match(encrypted)
        if m:
            self.scheme = m.group(1)
            self.password = m.group(2)
            self.plaintext = None
        else:
            # currently plaintext - encrypt
            self.setPassword(encrypted, scheme)
        if strict and self.scheme not in self.known_schemes:
            raise PasswordValueError, "unknown encryption scheme: %r" % (self.scheme,)

    def setPassword(self, plaintext, scheme=None):
        """Sets encrypts plaintext."""
        if scheme is None:
            scheme = self.default_scheme
        self.scheme = scheme
        self.password = encodePassword(plaintext, scheme)
        self.plaintext = plaintext

    def __cmp__(self, other):
        """Compare this password against another password."""
        # check to see if we're comparing instances
        if isinstance(other, Password):
            if self.scheme != other.scheme:
                return cmp(self.scheme, other.scheme)
            return cmp(self.password, other.password)

        # assume password is plaintext
        if self.password is None:
            raise ValueError, 'Password not set'
        return cmp(self.password, encodePassword(other, self.scheme,
            self.password))

    def __str__(self):
        """Stringify the encrypted password for database storage."""
        if self.password is None:
            raise ValueError, 'Password not set'
        return '{%s}%s'%(self.scheme, self.password)

def test():
    # SHA
    p = Password('sekrit')
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

    # MD5
    p = Password('sekrit', 'MD5')
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

    # crypt
    p = Password('sekrit', 'crypt')
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

    # PBKDF2 - low level function
    from binascii import unhexlify
    k = pbkdf2("password", "ATHENA.MIT.EDUraeburn", 1200, 32)
    assert k == unhexlify("5c08eb61fdf71e4e4ec3cf6ba1f5512ba7e52ddbc5e5142f708a31e2e62b1e13")

    # PBKDF2 - hash function
    h = "5000$7BvbBq.EZzz/O0HuwX3iP.nAG3s$g3oPnFFaga2BJaX5PoPRljl4XIE"
    assert encodePassword("sekrit", "PBKDF2", h) == h

    # PBKDF2 - high level integration
    p = Password('sekrit', 'PBKDF2')
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

if __name__ == '__main__':
    test()

# vim: set filetype=python sts=4 sw=4 et si :
