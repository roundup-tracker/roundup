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
# $Id: __init__.py,v 1.11 2002-02-16 08:39:42 richard Exp $

__all__ = []

try:
    import sys
    if not hasattr(sys, 'version_info') or sys.version_info < (2,1,2):
        import anydbm, dumbdbm
        # dumbdbm only works in python 2.1.2+
        assert anydbm._defaultmod != dumbdbm
        del anydbm
        del dumbdbm
    import back_anydbm
    anydbm = back_anydbm
    __all__.append('anydbm')
except AssertionError:
    pass
except ImportError:
    pass

try:
    import back_bsddb
    bsddb = back_bsddb
    __all__.append('bsddb')
except ImportError:
    pass

try:
    import back_bsddb3
    bsddb3 = back_bsddb3
    __all__.append('bsddb3')
except ImportError:
    pass

#
# $Log: not supported by cvs2svn $
# Revision 1.10  2002/01/22 07:08:50  richard
# I was certain I'd already done this (there's even a change note in
# CHANGES)...
#
# Revision 1.9  2001/12/12 02:30:51  richard
# I fixed the problems with people whose anydbm was using the dbm module at the
# backend. It turns out the dbm module modifies the file name to append ".db"
# and my check to determine if we're opening an existing or new db just
# tested os.path.exists() on the filename. Well, no longer! We now perform a
# much better check _and_ cope with the anydbm implementation module changing
# too!
# I also fixed the backends __init__ so only ImportError is squashed.
#
# Revision 1.8  2001/12/10 22:20:01  richard
# Enabled transaction support in the bsddb backend. It uses the anydbm code
# where possible, only replacing methods where the db is opened (it uses the
# btree opener specifically.)
# Also cleaned up some change note generation.
# Made the backends package work with pydoc too.
#
# Revision 1.7  2001/12/10 00:57:38  richard
# From CHANGES:
#  . Added the "display" command to the admin tool - displays a node's values
#  . #489760 ] [issue] only subject
#  . fixed the doc/index.html to include the quoting in the mail alias.
#
# Also:
#  . fixed roundup-admin so it works with transactions
#  . disabled the back_anydbm module if anydbm tries to use dumbdbm
#
# Revision 1.6  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.5  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
#
#
# vim: set filetype=python ts=4 sw=4 et si
