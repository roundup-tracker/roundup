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
# $Id: test_bsddb.py,v 1.1 2003-10-25 22:53:26 richard Exp $ 

import unittest, os, shutil, time

from db_test_base import DBTest, ROTest, SchemaTest, \
    ClassicInitTest
from roundup import backends

class bsddbOpener:
    if hasattr(backends, 'bsddb'):
        from roundup.backends import bsddb as module

class bsddbDBTest(bsddbOpener, DBTest):
    pass

class bsddbROTest(bsddbOpener, ROTest):
    pass

class bsddbSchemaTest(bsddbOpener, SchemaTest):
    pass

class bsddbClassicInitTest(ClassicInitTest):
    backend = 'bsddb'

def test_suite():
    suite = unittest.TestSuite()
    if not hasattr(backends, 'bsddb'):
        print 'Skipping bsddb tests'
        return suite
    print 'Including bsddb tests'
    suite.addTest(unittest.makeSuite(bsddbDBTest))
    suite.addTest(unittest.makeSuite(bsddbROTest))
    suite.addTest(unittest.makeSuite(bsddbSchemaTest))
    suite.addTest(unittest.makeSuite(bsddbClassicInitTest))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

