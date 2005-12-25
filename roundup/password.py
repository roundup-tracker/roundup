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

import sha, md5, re, string, random
try:
    import crypt
except:
    crypt = None
    pass

class PasswordValueError(ValueError):
    ''' The password value is not valid '''
    pass

def encodePassword(plaintext, scheme, other=None):
    '''Encrypt the plaintext password.
    '''
    if plaintext is None:
        plaintext = ""
    if scheme == 'SHA':
        s = sha.sha(plaintext).hexdigest()
    elif scheme == 'MD5':
        s = md5.md5(plaintext).hexdigest()
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
    '''The class encapsulates a Password property type value in the database.

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
    '''

    default_scheme = 'SHA'        # new encryptions use this scheme
    pwre = re.compile(r'{(\w+)}(.+)')

    def __init__(self, plaintext=None, scheme=None, encrypted=None):
        '''Call setPassword if plaintext is not None.'''
        if scheme is None:
            scheme = self.default_scheme
        if plaintext is not None:
            self.setPassword (plaintext, scheme)
        elif encrypted is not None:
            self.unpack(encrypted, scheme)
        else:
            self.scheme = self.default_scheme
            self.password = None
            self.plaintext = None

    def unpack(self, encrypted, scheme=None):
        '''Set the password info from the scheme:<encryted info> string
           (the inverse of __str__)
        '''
        m = self.pwre.match(encrypted)
        if m:
            self.scheme = m.group(1)
            self.password = m.group(2)
            self.plaintext = None
        else:
            # currently plaintext - encrypt
            self.setPassword(encrypted, scheme)

    def setPassword(self, plaintext, scheme=None):
        '''Sets encrypts plaintext.'''
        if scheme is None:
            scheme = self.default_scheme
        self.scheme = scheme
        self.password = encodePassword(plaintext, scheme)
        self.plaintext = plaintext

    def __cmp__(self, other):
        '''Compare this password against another password.'''
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
        '''Stringify the encrypted password for database storage.'''
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

if __name__ == '__main__':
    test()

# vim: set filetype=python sts=4 sw=4 et si :
