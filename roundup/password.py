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
# $Id: password.py,v 1.4 2001-11-22 15:46:42 jhermann Exp $

__doc__ = """
Password handling (encoding, decoding).
"""

import sha, re

def encodePassword(plaintext, scheme):
    '''Encrypt the plaintext password.
    '''
    if scheme == 'SHA':
        s = sha.sha(plaintext).hexdigest()
    elif scheme == 'plaintext':
        pass
    else:
        raise ValueError, 'Unknown encryption scheme "%s"'%scheme
    return s

class Password:
    '''The class encapsulates a Password property type value in the database. 

    The encoding of the password is one if None, 'SHA' or 'plaintext'. The
    encodePassword function is used to actually encode the password from
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

    def __init__(self, plaintext=None):
        '''Call setPassword if plaintext is not None.'''
        if plaintext is not None:
            self.password = encodePassword(plaintext, self.default_scheme)
            self.scheme = self.default_scheme
        else:
            self.password = None
            self.scheme = self.default_scheme

    def unpack(self, encrypted):
        '''Set the password info from the scheme:<encryted info> string
           (the inverse of __str__)
        '''
        m = self.pwre.match(encrypted)
        if m:
            self.scheme = m.group(1)
            self.password = m.group(2)
        else:
            # currently plaintext - encrypt
            self.password = encodePassword(encrypted, self.default_scheme)
            self.scheme = self.default_scheme

    def setPassword(self, plaintext):
        '''Sets encrypts plaintext.'''
        self.password = encodePassword(plaintext, self.scheme)

    def __cmp__(self, other):
        '''Compare this password against another password.'''
        # check to see if we're comparing instances
        if isinstance(other, Password):
            if self.scheme != other.scheme:
                return
            return cmp(self.password, other.password)

        # assume password is plaintext
        if self.password is None:
            raise ValueError, 'Password not set'
        return cmp(self.password, encodePassword(other, self.scheme))

    def __str__(self):
        '''Stringify the encrypted password for database storage.'''
        if self.password is None:
            raise ValueError, 'Password not set'
        return '{%s}%s'%(self.scheme, self.password)

def test():
    p = Password('sekrit')
    assert p == 'sekrit'
    assert p != 'not sekrit'
    assert 'sekrit' == p
    assert 'not sekrit' != p

if __name__ == '__main__':
    test()

#
# $Log: not supported by cvs2svn $
# Revision 1.3  2001/10/20 11:58:48  richard
# Catch errors in login - no username or password supplied.
# Fixed editing of password (Password property type) thanks Roch'e Compaan.
#
# Revision 1.2  2001/10/09 23:58:10  richard
# Moved the data stringification up into the hyperdb.Class class' get, set
# and create methods. This means that the data is also stringified for the
# journal call, and removes duplication of code from the backends. The
# backend code now only sees strings.
#
# Revision 1.1  2001/10/09 07:25:59  richard
# Added the Password property type. See "pydoc roundup.password" for
# implementation details. Have updated some of the documentation too.
#
#
#
# vim: set filetype=python ts=4 sw=4 et si
