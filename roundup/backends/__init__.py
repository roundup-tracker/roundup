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
# $Id: __init__.py,v 1.17 2002-09-18 05:07:47 richard Exp $

__all__ = []

try:
    import sys, anydbm
    if not hasattr(sys, 'version_info') or sys.version_info < (2,1,2):
        import dumbdbm
        # dumbdbm only works in python 2.1.2+
        assert anydbm._defaultmod != dumbdbm
        del anydbm
        del dumbdbm
except AssertionError:
    print "WARNING: you should upgrade to python 2.1.3"
except ImportError, message:
    if str(message) != 'No module named anydbm': raise
else:
    import back_anydbm
    anydbm = back_anydbm
    __all__.append('anydbm')

try:
    import gadfly
except ImportError, message:
    if str(message) != 'No module named gadfly': raise
else:
    import back_gadfly
    gadfly = back_gadfly
    __all__.append('gadfly')

try:
    import sqlite
except ImportError, message:
    if str(message) != 'No module named sqlite': raise
else:
    import back_sqlite
    sqlite = back_sqlite
    __all__.append('sqlite')

try:
    import bsddb
except ImportError, message:
    if str(message) != 'No module named bsddb': raise
else:
    import back_bsddb
    bsddb = back_bsddb
    __all__.append('bsddb')

try:
    import bsddb3
except ImportError, message:
    if str(message) != 'No module named bsddb3': raise
else:
    import back_bsddb3
    bsddb3 = back_bsddb3
    __all__.append('bsddb3')

try:
    import metakit
except ImportError, message:
    if str(message) != 'No module named metakit': raise
else:
    import back_metakit
    metakit = back_metakit
    __all__.append('metakit')

# vim: set filetype=python ts=4 sw=4 et si
