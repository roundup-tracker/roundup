#
# Copyright (c) 2003 Richard Jones, rjones@ekit-inc.com
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# $Id: test_cgi.py,v 1.9 2003-02-14 00:31:46 richard Exp $

import unittest, os, shutil, errno, sys, difflib, cgi

from roundup.cgi import client
from roundup import init, instance, password, hyperdb, date

class FileUpload:
    def __init__(self, content, filename):
        self.content = content
        self.filename = filename

def makeForm(args):
    form = cgi.FieldStorage()
    for k,v in args.items():
        if type(v) is type([]):
            [form.list.append(cgi.MiniFieldStorage(k, x)) for x in v]
        elif isinstance(v, FileUpload):
            x = cgi.MiniFieldStorage(k, v.content)
            x.filename = v.filename
            form.list.append(x)
        else:
            form.list.append(cgi.MiniFieldStorage(k, v))
    return form

class config:
    TRACKER_NAME = 'testing testing'
    TRACKER_WEB = 'http://testing.testing/'

class FormTestCase(unittest.TestCase):
    def setUp(self):
        self.dirname = '_test_cgi_form'
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise
        # create the instance
        init.install(self.dirname, 'classic', 'anydbm')
        init.initialise(self.dirname, 'sekrit')
        # check we can load the package
        self.instance = instance.open(self.dirname)
        # and open the database
        self.db = self.instance.open('admin')
        self.db.user.create(username='Chef', address='chef@bork.bork.bork',
            realname='Bork, Chef', roles='User')
        self.db.user.create(username='mary', address='mary@test',
            roles='User', realname='Contrary, Mary')

        test = self.instance.dbinit.Class(self.db, "test",
            string=hyperdb.String(),
            boolean=hyperdb.Boolean(), link=hyperdb.Link('test'),
            multilink=hyperdb.Multilink('test'), date=hyperdb.Date(),
            interval=hyperdb.Interval())

    def parseForm(self, form, classname='test', nodeid=None):
        cl = client.Client(self.instance, None, {'PATH_INFO':'/'},
            makeForm(form))
        cl.classname = classname
        cl.nodeid = nodeid
        cl.db = self.db
        return cl.parsePropsFromForm()

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    #
    # Empty form
    #
    def testNothing(self):
        self.assertEqual(self.parseForm({}), ({('test', None): {}}, []))

    def testNothingWithRequired(self):
        self.assertRaises(ValueError, self.parseForm, {':required': 'string'})
        self.assertRaises(ValueError, self.parseForm,
            {':required': 'title,status', 'status':'1'}, 'issue')
        self.assertRaises(ValueError, self.parseForm,
            {':required': ['title','status'], 'status':'1'}, 'issue')
        self.assertRaises(ValueError, self.parseForm,
            {':required': 'status', 'status':''}, 'issue')
        self.assertRaises(ValueError, self.parseForm,
            {':required': 'nosy', 'nosy':''}, 'issue')

    #
    # Nonexistant edit
    #
    def testEditNonexistant(self):
        self.assertRaises(IndexError, self.parseForm, {'boolean': ''},
            'test', '1')

    #
    # String
    #
    def testEmptyString(self):
        self.assertEqual(self.parseForm({'string': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'string': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(ValueError, self.parseForm, {'string': ['', '']})

    def testSetString(self):
        self.assertEqual(self.parseForm({'string': 'foo'}),
            ({('test', None): {'string': 'foo'}}, []))
        self.assertEqual(self.parseForm({'string': 'a\r\nb\r\n'}),
            ({('test', None): {'string': 'a\nb'}}, []))
        nodeid = self.db.issue.create(title='foo')
        self.assertEqual(self.parseForm({'title': 'foo'}, 'issue', nodeid),
            ({('issue', nodeid): {}}, []))

    def testEmptyStringSet(self):
        nodeid = self.db.issue.create(title='foo')
        self.assertEqual(self.parseForm({'title': ''}, 'issue', nodeid),
            ({('issue', nodeid): {'title': None}}, []))
        nodeid = self.db.issue.create(title='foo')
        self.assertEqual(self.parseForm({'title': ' '}, 'issue', nodeid),
            ({('issue', nodeid): {'title': None}}, []))

    def testFileUpload(self):
        file = FileUpload('foo', 'foo.txt')
        self.assertEqual(self.parseForm({'content': file}, 'file'),
            ({('file', None): {'content': 'foo', 'name': 'foo.txt',
            'type': 'text/plain'}}, []))

    #
    # Link
    #
    def testEmptyLink(self):
        self.assertEqual(self.parseForm({'link': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'link': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(ValueError, self.parseForm, {'link': ['', '']})
        self.assertEqual(self.parseForm({'link': '-1'}),
            ({('test', None): {}}, []))

    def testSetLink(self):
        self.assertEqual(self.parseForm({'status': 'unread'}, 'issue'),
            ({('issue', None): {'status': '1'}}, []))
        self.assertEqual(self.parseForm({'status': '1'}, 'issue'),
            ({('issue', None): {'status': '1'}}, []))
        nodeid = self.db.issue.create(status='unread')
        self.assertEqual(self.parseForm({'status': 'unread'}, 'issue', nodeid),
            ({('issue', nodeid): {}}, []))

    def testUnsetLink(self):
        nodeid = self.db.issue.create(status='unread')
        self.assertEqual(self.parseForm({'status': '-1'}, 'issue', nodeid),
            ({('issue', nodeid): {'status': None}}, []))

    def testInvalidLinkValue(self):
# XXX This is not the current behaviour - should we enforce this?
#        self.assertRaises(IndexError, self.parseForm,
#            {'status': '4'}))
        self.assertRaises(ValueError, self.parseForm, {'link': 'frozzle'})
        self.assertRaises(ValueError, self.parseForm, {'status': 'frozzle'},
            'issue')

    #
    # Multilink
    #
    def testEmptyMultilink(self):
        self.assertEqual(self.parseForm({'nosy': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'nosy': ' '}),
            ({('test', None): {}}, []))

    def testSetMultilink(self):
        self.assertEqual(self.parseForm({'nosy': '1'}, 'issue'),
            ({('issue', None): {'nosy': ['1']}}, []))
        self.assertEqual(self.parseForm({'nosy': 'admin'}, 'issue'),
            ({('issue', None): {'nosy': ['1']}}, []))
        self.assertEqual(self.parseForm({'nosy': ['1','2']}, 'issue'),
            ({('issue', None): {'nosy': ['1','2']}}, []))
        self.assertEqual(self.parseForm({'nosy': '1,2'}, 'issue'),
            ({('issue', None): {'nosy': ['1','2']}}, []))
        self.assertEqual(self.parseForm({'nosy': 'admin,2'}, 'issue'),
            ({('issue', None): {'nosy': ['1','2']}}, []))

    def testEmptyMultilinkSet(self):
        nodeid = self.db.issue.create(nosy=['1','2'])
        self.assertEqual(self.parseForm({'nosy': ''}, 'issue', nodeid), 
            ({('issue', nodeid): {'nosy': []}}, []))
        nodeid = self.db.issue.create(nosy=['1','2'])
        self.assertEqual(self.parseForm({'nosy': ' '}, 'issue', nodeid), 
            ({('issue', nodeid): {'nosy': []}}, []))
        self.assertEqual(self.parseForm({'nosy': '1,2'}, 'issue', nodeid),
            ({('issue', nodeid): {}}, []))

    def testInvalidMultilinkValue(self):
# XXX This is not the current behaviour - should we enforce this?
#        self.assertRaises(IndexError, self.parseForm,
#            {'nosy': '4'}))
        self.assertRaises(ValueError, self.parseForm, {'nosy': 'frozzle'},
            'issue')
        self.assertRaises(ValueError, self.parseForm, {'nosy': '1,frozzle'},
            'issue')
        self.assertRaises(ValueError, self.parseForm, {'multilink': 'frozzle'})

    def testMultilinkAdd(self):
        nodeid = self.db.issue.create(nosy=['1'])
        # do nothing
        self.assertEqual(self.parseForm({':add:nosy': ''}, 'issue', nodeid),
            ({('issue', nodeid): {}}, []))

        # do something ;)
        self.assertEqual(self.parseForm({':add:nosy': '2'}, 'issue', nodeid),
            ({('issue', nodeid): {'nosy': ['1','2']}}, []))
        self.assertEqual(self.parseForm({':add:nosy': '2,mary'}, 'issue',
            nodeid), ({('issue', nodeid): {'nosy': ['1','2','4']}}, []))
        self.assertEqual(self.parseForm({':add:nosy': ['2','3']}, 'issue',
            nodeid), ({('issue', nodeid): {'nosy': ['1','2','3']}}, []))

    def testMultilinkAddNew(self):
        self.assertEqual(self.parseForm({':add:nosy': ['2','3']}, 'issue'),
            ({('issue', None): {'nosy': ['2','3']}}, []))

    def testMultilinkRemove(self):
        nodeid = self.db.issue.create(nosy=['1','2'])
        # do nothing
        self.assertEqual(self.parseForm({':remove:nosy': ''}, 'issue', nodeid),
            ({('issue', nodeid): {}}, []))

        # do something ;)
        self.assertEqual(self.parseForm({':remove:nosy': '1'}, 'issue',
            nodeid), ({('issue', nodeid): {'nosy': ['2']}}, []))
        self.assertEqual(self.parseForm({':remove:nosy': 'admin,2'},
            'issue', nodeid), ({('issue', nodeid): {'nosy': []}}, []))
        self.assertEqual(self.parseForm({':remove:nosy': ['1','2']},
            'issue', nodeid), ({('issue', nodeid): {'nosy': []}}, []))

        # add and remove
        self.assertEqual(self.parseForm({':add:nosy': ['3'],
            ':remove:nosy': ['1','2']},
            'issue', nodeid), ({('issue', nodeid): {'nosy': ['3']}}, []))

        # remove one that doesn't exist?
        self.assertRaises(ValueError, self.parseForm, {':remove:nosy': '4'},
            'issue', nodeid)

    def testMultilinkRetired(self):
        self.db.user.retire('2')
        self.assertEqual(self.parseForm({'nosy': ['2','3']}, 'issue'),
            ({('issue', None): {'nosy': ['2','3']}}, []))
        nodeid = self.db.issue.create(nosy=['1','2'])
        self.assertEqual(self.parseForm({':remove:nosy': '2'}, 'issue',
            nodeid), ({('issue', nodeid): {'nosy': ['1']}}, []))
        self.assertEqual(self.parseForm({':add:nosy': '3'}, 'issue', nodeid),
            ({('issue', nodeid): {'nosy': ['1','2','3']}}, []))

    def testAddRemoveNonexistant(self):
        self.assertRaises(ValueError, self.parseForm, {':remove:foo': '2'},
            'issue')
        self.assertRaises(ValueError, self.parseForm, {':add:foo': '2'},
            'issue')

    #
    # Password
    #
    def testEmptyPassword(self):
        self.assertEqual(self.parseForm({'password': ''}, 'user'),
            ({('user', None): {}}, []))
        self.assertEqual(self.parseForm({'password': ''}, 'user'),
            ({('user', None): {}}, []))
        self.assertRaises(ValueError, self.parseForm, {'password': ['', '']},
            'user')
        self.assertRaises(ValueError, self.parseForm, {'password': 'foo',
            'password:confirm': ['', '']}, 'user')

    def testSetPassword(self):
        self.assertEqual(self.parseForm({'password': 'foo',
            'password:confirm': 'foo'}, 'user'),
            ({('user', None): {'password': 'foo'}}, []))

    def testSetPasswordConfirmBad(self):
        self.assertRaises(ValueError, self.parseForm, {'password': 'foo'},
            'user')
        self.assertRaises(ValueError, self.parseForm, {'password': 'foo',
            'password:confirm': 'bar'}, 'user')

    def testEmptyPasswordNotSet(self):
        nodeid = self.db.user.create(username='1',
            password=password.Password('foo'))
        self.assertEqual(self.parseForm({'password': ''}, 'user', nodeid),
            ({('user', nodeid): {}}, []))
        nodeid = self.db.user.create(username='2',
            password=password.Password('foo'))
        self.assertEqual(self.parseForm({'password': '',
            'password:confirm': ''}, 'user', nodeid),
            ({('user', nodeid): {}}, []))

    #
    # Boolean
    #
    def testEmptyBoolean(self):
        self.assertEqual(self.parseForm({'boolean': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'boolean': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(ValueError, self.parseForm, {'boolean': ['', '']})

    def testSetBoolean(self):
        self.assertEqual(self.parseForm({'boolean': 'yes'}),
            ({('test', None): {'boolean': 1}}, []))
        self.assertEqual(self.parseForm({'boolean': 'a\r\nb\r\n'}),
            ({('test', None): {'boolean': 0}}, []))
        nodeid = self.db.test.create(boolean=1)
        self.assertEqual(self.parseForm({'boolean': 'yes'}, 'test', nodeid),
            ({('test', nodeid): {}}, []))
        nodeid = self.db.test.create(boolean=0)
        self.assertEqual(self.parseForm({'boolean': 'no'}, 'test', nodeid),
            ({('test', nodeid): {}}, []))

    def testEmptyBooleanSet(self):
        nodeid = self.db.test.create(boolean=0)
        self.assertEqual(self.parseForm({'boolean': ''}, 'test', nodeid),
            ({('test', nodeid): {'boolean': None}}, []))
        nodeid = self.db.test.create(boolean=1)
        self.assertEqual(self.parseForm({'boolean': ' '}, 'test', nodeid),
            ({('test', nodeid): {'boolean': None}}, []))

    #
    # Date
    #
    def testEmptyDate(self):
        self.assertEqual(self.parseForm({'date': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'date': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(ValueError, self.parseForm, {'date': ['', '']})

    def testSetDate(self):
        self.assertEqual(self.parseForm({'date': '2003-01-01'}),
            ({('test', None): {'date': date.Date('2003-01-01')}}, []))
        nodeid = self.db.test.create(date=date.Date('2003-01-01'))
        self.assertEqual(self.parseForm({'date': '2003-01-01'}, 'test', 
            nodeid), ({('test', nodeid): {}}, []))

    def testEmptyDateSet(self):
        nodeid = self.db.test.create(date=date.Date('.'))
        self.assertEqual(self.parseForm({'date': ''}, 'test', nodeid), 
            ({('test', nodeid): {'date': None}}, []))
        nodeid = self.db.test.create(date=date.Date('1970-01-01.00:00:00'))
        self.assertEqual(self.parseForm({'date': ' '}, 'test', nodeid), 
            ({('test', nodeid): {'date': None}}, []))

    #
    # Test multiple items in form
    #
    def testMultiple(self):
        self.assertEqual(self.parseForm({'string': 'a', 'issue-1@title': 'b'}),
            ({('test', None): {'string': 'a'}, ('issue', '-1'):
            {'title': 'b'}}, []))
        nodeid = self.db.test.create()
        self.assertEqual(self.parseForm({'string': 'a', 'issue-1@title': 'b'},
            'test', nodeid), ({('test', nodeid): {'string': 'a'},
            ('issue', '-1'): {'title': 'b'}}, []))
        self.assertEqual(self.parseForm({
            'string': 'a',
            'issue-1@:add:nosy': '1',
            'issue-2@:link:superseder': 'issue-1',
            }),
            ({('test', None): {'string': 'a'},
              ('issue', '-1'): {'nosy': ['1']},
              ('issue', '-2'): {}},
              [('issue', '-2', 'superseder',
                [(('issue', '-1'), ('issue', '-1'))])
              ]
            )
        )

    def testLinkBadDesignator(self):
        self.assertRaises(ValueError, self.parseForm,
            {'test-1@:link:link': 'blah'})
        self.assertRaises(ValueError, self.parseForm,
            {'test-1@:link:link': 'issue'})

    def testBackwardsCompat(self):
        res = self.parseForm({':note': 'spam'}, 'issue')
        date = res[0][('msg', '-1')]['date']
        self.assertEqual(res, ({('issue', None): {}, ('msg', '-1'):
            {'content': 'spam', 'author': '1', 'date': date}},
            [('issue', None, 'messages', [('msg', '-1')])]))
        file = FileUpload('foo', 'foo.txt')
        self.assertEqual(self.parseForm({':file': file}, 'issue'),
            ({('issue', None): {}, ('file', '-1'): {'content': 'foo',
            'name': 'foo.txt', 'type': 'text/plain'}},
            [('issue', None, 'files', [('file', '-1')])]))

def suite():
    l = [unittest.makeSuite(FormTestCase),
    ]
    return unittest.TestSuite(l)

def run():
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

if __name__ == '__main__':
    run()

# vim: set filetype=python ts=4 sw=4 et si
