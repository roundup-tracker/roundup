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
# $Id: test_init.py,v 1.19 2002-09-18 05:07:49 richard Exp $

import unittest, os, shutil, errno, imp, sys

from roundup import init

class MyTestCase(unittest.TestCase):
    count = 0
    def setUp(self):
        MyTestCase.count = MyTestCase.count + 1
        self.dirname = '_test_init_%s'%self.count
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def tearDown(self):
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

class ClassicTestCase(MyTestCase):
    backend = 'anydbm'
    def testCreation(self):
        ae = self.assertEqual

        # create the instance
        init.install(self.dirname, 'classic', self.backend)
        init.initialise(self.dirname, 'sekrit')

        # check we can load the package
        instance = imp.load_package(self.dirname, self.dirname)

        # and open the database
        db = instance.open()

        # check the basics of the schema and initial data set
        l = db.priority.list()
        ae(l, ['1', '2', '3', '4', '5'])
        l = db.status.list()
        ae(l, ['1', '2', '3', '4', '5', '6', '7', '8'])
        l = db.keyword.list()
        ae(l, [])
        l = db.user.list()
        ae(l, ['1', '2'])
        l = db.msg.list()
        ae(l, [])
        l = db.file.list()
        ae(l, [])
        l = db.issue.list()
        ae(l, [])

class bsddbClassicTestCase(ClassicTestCase):
    backend = 'bsddb'

class bsddb3ClassicTestCase(ClassicTestCase):
    backend = 'bsddb3'

class metakitClassicTestCase(ClassicTestCase):
    backend = 'metakit'

class gadflyClassicTestCase(ClassicTestCase):
    backend = 'gadfly'

class sqliteClassicTestCase(ClassicTestCase):
    backend = 'sqlite'

def suite():
    l = [
        unittest.makeSuite(ClassicTestCase, 'test'),
    ]

    try:
        import bsddb
        l.append(unittest.makeSuite(bsddbClassicTestCase, 'test'))
    except:
        print 'bsddb module not found, skipping bsddb init test'

    try:
        import bsddb3
        l.append(unittest.makeSuite(bsddb3ClassicTestCase, 'test'))
    except:
        print 'bsddb3 module not found, skipping bsddb3 init test'

    try:
        import metakit
        l.append(unittest.makeSuite(metakitClassicTestCase, 'test'))
    except:
        print 'metakit module not found, skipping metakit init test'

    try:
        import gadfly
        l.append(unittest.makeSuite(gadflyClassicTestCase, 'test'))
    except:
        print 'gadfly module not found, skipping gadfly init test'

    try:
        import sqlite
        l.append(unittest.makeSuite(sqliteClassicTestCase, 'test'))
    except:
        print 'sqlite module not found, skipping sqlite init test'

    return unittest.TestSuite(l)

# vim: set filetype=python ts=4 sw=4 et si
