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
# $Id: test_schema.py,v 1.8 2002-07-14 02:05:54 richard Exp $ 

import unittest, os, shutil

from roundup.backends import back_anydbm
from roundup.hyperdb import String, Password, Link, Multilink, Date, \
    Interval

class config:
    DATABASE='_test_dir'
    MAILHOST = 'localhost'
    MAIL_DOMAIN = 'fill.me.in.'
    INSTANCE_NAME = 'Roundup issue tracker'
    ISSUE_TRACKER_EMAIL = 'issue_tracker@%s'%MAIL_DOMAIN
    ISSUE_TRACKER_WEB = 'http://some.useful.url/'
    ADMIN_EMAIL = 'roundup-admin@%s'%MAIL_DOMAIN
    FILTER_POSITION = 'bottom'      # one of 'top', 'bottom', 'top and bottom'
    ANONYMOUS_ACCESS = 'deny'       # either 'deny' or 'allow'
    ANONYMOUS_REGISTER = 'deny'     # either 'deny' or 'allow'
    MESSAGES_TO_AUTHOR = 'no'       # either 'yes' or 'no'
    EMAIL_SIGNATURE_POSITION = 'bottom'

class SchemaTestCase(unittest.TestCase):
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = back_anydbm.Database(config, 'test')
        self.db.clear()

    def tearDown(self):
        shutil.rmtree('_test_dir')

    def testA_Status(self):
        status = back_anydbm.Class(self.db, "status", name=String())
        self.assert_(status, 'no class object generated')
        status.setkey("name")
        val = status.create(name="unread")
        self.assertEqual(val, '1', 'expecting "1"')
        val = status.create(name="in-progress")
        self.assertEqual(val, '2', 'expecting "2"')
        val = status.create(name="testing")
        self.assertEqual(val, '3', 'expecting "3"')
        val = status.create(name="resolved")
        self.assertEqual(val, '4', 'expecting "4"')
        val = status.count()
        self.assertEqual(val, 4, 'expecting 4')
        val = status.list()
        self.assertEqual(val, ['1', '2', '3', '4'], 'blah')
        val = status.lookup("in-progress")
        self.assertEqual(val, '2', 'expecting "2"')
        status.retire('3')
        val = status.list()
        self.assertEqual(val, ['1', '2', '4'], 'blah')

    def testB_Issue(self):
        issue = back_anydbm.Class(self.db, "issue", title=String(),
            status=Link("status"))
        self.assert_(issue, 'no class object returned')

    def testC_User(self):
        user = back_anydbm.Class(self.db, "user", username=String(),
            password=Password())
        self.assert_(user, 'no class object returned')
        user.setkey("username")


def suite():
   return unittest.makeSuite(SchemaTestCase, 'test')


#
# $Log: not supported by cvs2svn $
# Revision 1.7  2002/01/14 02:20:15  richard
#  . changed all config accesses so they access either the instance or the
#    config attriubute on the db. This means that all config is obtained from
#    instance_config instead of the mish-mash of classes. This will make
#    switching to a ConfigParser setup easier too, I hope.
#
# At a minimum, this makes migration a _little_ easier (a lot easier in the
# 0.5.0 switch, I hope!)
#
# Revision 1.6  2001/12/03 21:33:39  richard
# Fixes so the tests use commit and not close
#
# Revision 1.5  2001/10/09 07:25:59  richard
# Added the Password property type. See "pydoc roundup.password" for
# implementation details. Have updated some of the documentation too.
#
# Revision 1.4  2001/08/07 00:24:43  richard
# stupid typo
#
# Revision 1.3  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.2  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.1  2001/07/27 06:55:07  richard
# moving tests -> test
#
# Revision 1.3  2001/07/25 04:34:31  richard
# Added id and log to tests files...
#
#
# vim: set filetype=python ts=4 sw=4 et si
