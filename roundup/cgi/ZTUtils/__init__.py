##############################################################################
#
# Copyright (c) 2001 Zope Corporation and Contributors. All Rights Reserved.
# 
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
# 
##############################################################################
__doc__='''Package of template utility classes and functions.

Modified for Roundup 0.5 release:

- removed Zope imports

$Id: __init__.py,v 1.3 2004-02-11 23:55:09 richard Exp $'''
__docformat__ = 'restructuredtext'
__version__='$Revision: 1.3 $'[11:-2]

from Batch import Batch
from Iterator import Iterator

