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
# $Id: test_db.py,v 1.10 2001-12-03 21:33:39 richard Exp $ 

import unittest, os, shutil

from roundup.hyperdb import String, Password, Link, Multilink, Date, \
    Interval, Class, DatabaseError

def setupSchema(db, create):
    status = Class(db, "status", name=String())
    status.setkey("name")
    if create:
        status.create(name="unread")
        status.create(name="in-progress")
        status.create(name="testing")
        status.create(name="resolved")
    Class(db, "user", username=String(), password=Password())
    Class(db, "issue", title=String(), status=Link("status"),
        nosy=Multilink("user"))

#class MyTestResult(unittest._TestResult):
#    def addError(self, test, err):
#        print `err`
#        TestResult.addError(self, test, err)
#        if self.showAll:
#            self.stream.writeln("ERROR")
#        elif self.dots:
#            self.stream.write('E')
#        if err[0] is KeyboardInterrupt:
#            self.shouldStop = 1

class MyTestCase(unittest.TestCase):
#    def defaultTestResult(self):
#        return MyTestResult()
    def tearDown(self):
        if self.db is not None:
            shutil.rmtree('_test_dir')
    
class DBTestCase(MyTestCase):
    def setUp(self):
        from roundup.backends import anydbm
        # remove previous test, ignore errors
        if os.path.exists('_test_dir'):
            shutil.rmtree('_test_dir')
        os.mkdir('_test_dir')
        self.db = anydbm.Database('_test_dir', 'test')
        setupSchema(self.db, 1)

    def testChanges(self):
        self.db.issue.create(title="spam", status='1')
        self.db.issue.create(title="eggs", status='2')
        self.db.issue.create(title="ham", status='4')
        self.db.issue.create(title="arguments", status='2')
        self.db.issue.create(title="abuse", status='1')
        self.db.issue.addprop(fixer=Link("user"))
        props = self.db.issue.getprops()
        keys = props.keys()
        keys.sort()
        self.assertEqual(keys, ['fixer', 'id', 'nosy', 'status', 'title'])
        self.db.issue.set('5', status='2')
        self.db.issue.get('5', "status")
        self.db.status.get('2', "name")
        self.db.issue.get('5', "title")
        self.db.issue.find(status = self.db.status.lookup("in-progress"))
        self.db.commit()
        self.db.issue.history('5')
        self.db.status.history('1')
        self.db.status.history('2')

    def testExceptions(self):
        # this tests the exceptions that should be raised
        ar = self.assertRaises

        #
        # class create
        #
        # string property
        ar(TypeError, self.db.status.create, name=1)
        # invalid property name
        ar(KeyError, self.db.status.create, foo='foo')
        # key name clash
        ar(ValueError, self.db.status.create, name='unread')
        # invalid link index
        ar(IndexError, self.db.issue.create, title='foo', status='bar')
        # invalid link value
        ar(ValueError, self.db.issue.create, title='foo', status=1)
        # invalid multilink type
        ar(TypeError, self.db.issue.create, title='foo', status='1',
            nosy='hello')
        # invalid multilink index type
        ar(ValueError, self.db.issue.create, title='foo', status='1',
            nosy=[1])
        # invalid multilink index
        ar(IndexError, self.db.issue.create, title='foo', status='1',
            nosy=['10'])

        #
        # class get
        #
        # invalid node id
        ar(IndexError, self.db.status.get, '10', 'name')
        # invalid property name
        ar(KeyError, self.db.status.get, '2', 'foo')

        #
        # class set
        #
        # invalid node id
        ar(IndexError, self.db.issue.set, '1', name='foo')
        # invalid property name
        ar(KeyError, self.db.status.set, '1', foo='foo')
        # string property
        ar(TypeError, self.db.status.set, '1', name=1)
        # key name clash
        ar(ValueError, self.db.status.set, '2', name='unread')
        # set up a valid issue for me to work on
        self.db.issue.create(title="spam", status='1')
        # invalid link index
        ar(IndexError, self.db.issue.set, '1', title='foo', status='bar')
        # invalid link value
        ar(ValueError, self.db.issue.set, '1', title='foo', status=1)
        # invalid multilink type
        ar(TypeError, self.db.issue.set, '1', title='foo', status='1',
            nosy='hello')
        # invalid multilink index type
        ar(ValueError, self.db.issue.set, '1', title='foo', status='1',
            nosy=[1])
        # invalid multilink index
        ar(IndexError, self.db.issue.set, '1', title='foo', status='1',
            nosy=['10'])

    def testRetire(self):
        pass


class ReadOnlyDBTestCase(MyTestCase):
    def setUp(self):
        from roundup.backends import anydbm
        # remove previous test, ignore errors
        if os.path.exists('_test_dir'):
            shutil.rmtree('_test_dir')
        os.mkdir('_test_dir')
        db = anydbm.Database('_test_dir', 'test')
        setupSchema(db, 1)
        self.db = anydbm.Database('_test_dir')
        setupSchema(self.db, 0)

    def testExceptions(self):
        # this tests the exceptions that should be raised
        ar = self.assertRaises

        # this tests the exceptions that should be raised
        ar(DatabaseError, self.db.status.create, name="foo")
        ar(DatabaseError, self.db.status.set, '1', name="foo")
        ar(DatabaseError, self.db.status.retire, '1')


class bsddbDBTestCase(DBTestCase):
    def setUp(self):
        from roundup.backends import bsddb
        # remove previous test, ignore errors
        if os.path.exists('_test_dir'):
            shutil.rmtree('_test_dir')
        os.mkdir('_test_dir')
        self.db = bsddb.Database('_test_dir', 'test')
        setupSchema(self.db, 1)

class bsddbReadOnlyDBTestCase(ReadOnlyDBTestCase):
    def setUp(self):
        from roundup.backends import bsddb
        # remove previous test, ignore errors
        if os.path.exists('_test_dir'):
            shutil.rmtree('_test_dir')
        os.mkdir('_test_dir')
        db = bsddb.Database('_test_dir', 'test')
        setupSchema(db, 1)
        self.db = bsddb.Database('_test_dir')
        setupSchema(self.db, 0)


class bsddb3DBTestCase(DBTestCase):
    def setUp(self):
        from roundup.backends import bsddb3
        # remove previous test, ignore errors
        if os.path.exists('_test_dir'):
            shutil.rmtree('_test_dir')
        os.mkdir('_test_dir')
        self.db = bsddb3.Database('_test_dir', 'test')
        setupSchema(self.db, 1)

class bsddb3ReadOnlyDBTestCase(ReadOnlyDBTestCase):
    def setUp(self):
        from roundup.backends import bsddb3
        # remove previous test, ignore errors
        if os.path.exists('_test_dir'):
            shutil.rmtree('_test_dir')
        os.mkdir('_test_dir')
        db = bsddb3.Database('_test_dir', 'test')
        setupSchema(db, 1)
        self.db = bsddb3.Database('_test_dir')
        setupSchema(self.db, 0)


def suite():
    l = [unittest.makeSuite(DBTestCase, 'test'),
         unittest.makeSuite(ReadOnlyDBTestCase, 'test')]

    try:
        import bsddb
        l.append(unittest.makeSuite(bsddbDBTestCase, 'test'))
        l.append(unittest.makeSuite(bsddbReadOnlyDBTestCase, 'test'))
    except:
        print 'bsddb module not found, skipping bsddb DBTestCase'

#    try:
#        import bsddb3
#        l.append(unittest.makeSuite(bsddb3DBTestCase, 'test'))
#        l.append(unittest.makeSuite(bsddb3ReadOnlyDBTestCase, 'test'))
#    except:
#        print 'bsddb3 module not found, skipping bsddb3 DBTestCase'

    return unittest.TestSuite(l)

#
# $Log: not supported by cvs2svn $
# Revision 1.9  2001/12/02 05:06:16  richard
# . We now use weakrefs in the Classes to keep the database reference, so
#   the close() method on the database is no longer needed.
#   I bumped the minimum python requirement up to 2.1 accordingly.
# . #487480 ] roundup-server
# . #487476 ] INSTALL.txt
#
# I also cleaned up the change message / post-edit stuff in the cgi client.
# There's now a clearly marked "TODO: append the change note" where I believe
# the change note should be added there. The "changes" list will obviously
# have to be modified to be a dict of the changes, or somesuch.
#
# More testing needed.
#
# Revision 1.8  2001/10/09 07:25:59  richard
# Added the Password property type. See "pydoc roundup.password" for
# implementation details. Have updated some of the documentation too.
#
# Revision 1.7  2001/08/29 06:23:59  richard
# Disabled the bsddb3 module entirely in the unit testing. See CHANGES for
# details.
#
# Revision 1.6  2001/08/07 00:24:43  richard
# stupid typo
#
# Revision 1.5  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.4  2001/07/30 03:45:56  richard
# Added more DB to test_db. Can skip tests where imports fail.
#
# Revision 1.3  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.2  2001/07/29 04:09:20  richard
# Added the fabricated property "id" to all hyperdb classes.
#
# Revision 1.1  2001/07/27 06:55:07  richard
# moving tests -> test
#
# Revision 1.7  2001/07/27 06:26:43  richard
# oops - wasn't deleting the test dir after the read-only tests
#
# Revision 1.6  2001/07/27 06:23:59  richard
# consistency
#
# Revision 1.5  2001/07/27 06:23:09  richard
# Added some new hyperdb tests to make sure we raise the right exceptions.
#
# Revision 1.4  2001/07/25 04:34:31  richard
# Added id and log to tests files...
#
#
# vim: set filetype=python ts=4 sw=4 et si
