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
# $Id: test_bsddb3.py,v 1.3 2004-03-18 01:58:46 richard Exp $ 

import unittest, os, shutil, time

from db_test_base import DBTest, ROTest, SchemaTest, ClassicInitTest, config
from roundup import backends

class bsddb3Opener:
    if hasattr(backends, 'bsddb3'):
        from roundup.backends import bsddb3 as module

    def nuke_database(self):
        shutil.rmtree(config.DATABASE)

class bsddb3DBTest(bsddb3Opener, DBTest):
    pass

class bsddb3ROTest(bsddb3Opener, ROTest):
    pass

class bsddb3SchemaTest(bsddb3Opener, SchemaTest):
    pass

class bsddb3ClassicInitTest(ClassicInitTest):
    backend = 'bsddb3'

from session_common import DBMTest
class bsddb3SessionTest(bsddb3Opener, DBMTest):
    pass

def test_suite():
    suite = unittest.TestSuite()
    if not hasattr(backends, 'bsddb3'):
        print 'Skipping bsddb3 tests'
        return suite
    print 'Including bsddb3 tests'
    suite.addTest(unittest.makeSuite(bsddb3DBTest))
    suite.addTest(unittest.makeSuite(bsddb3ROTest))
    suite.addTest(unittest.makeSuite(bsddb3SchemaTest))
    suite.addTest(unittest.makeSuite(bsddb3ClassicInitTest))
    suite.addTest(unittest.makeSuite(bsddb3SessionTest))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

