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
# $Id: __init__.py,v 1.8 2001-12-10 22:20:01 richard Exp $

__all__ = []

try:
    import anydbm, dumbdbm
    # dumbdbm in python 2,2b2, 2.1.1 and earlier is seriously broken
    assert anydbm._defaultmod != dumbdbm
    del anydbm
    del dumbdbm
    import back_anydbm
    anydbm = back_anydbm
    __all__.append('anydbm')
except AssertionError:
    del back_anydbm
except:
    pass

try:
    import back_bsddb
    bsddb = back_bsddb
    __all__.append('bsddb')
except:
    pass

try:
    import back_bsddb3
    bsddb3 = back_bsddb3
    __all__.append('bsddb3')
except:
    pass

#
# $Log: not supported by cvs2svn $
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
