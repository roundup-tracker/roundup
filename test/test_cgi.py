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
# $Id: test_cgi.py,v 1.36 2008-08-07 06:12:57 richard Exp $

import unittest, os, shutil, errno, sys, difflib, cgi, re

from roundup.cgi import client, actions, exceptions
from roundup.cgi.exceptions import FormError
from roundup.cgi.templating import HTMLItem
from roundup.cgi.form_parser import FormParser
from roundup import init, instance, password, hyperdb, date

import db_test_base

NEEDS_INSTANCE = 1

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

cm = client.clean_message
class MessageTestCase(unittest.TestCase):
    def testCleanMessageOK(self):
        self.assertEqual(cm('<br>x<br />'), '<br>x<br />')
        self.assertEqual(cm('<i>x</i>'), '<i>x</i>')
        self.assertEqual(cm('<b>x</b>'), '<b>x</b>')
        self.assertEqual(cm('<a href="y">x</a>'),
            '<a href="y">x</a>')
        self.assertEqual(cm('<BR>x<BR />'), '<BR>x<BR />')
        self.assertEqual(cm('<I>x</I>'), '<I>x</I>')
        self.assertEqual(cm('<B>x</B>'), '<B>x</B>')
        self.assertEqual(cm('<A HREF="y">x</A>'),
            '<A HREF="y">x</A>')

    def testCleanMessageBAD(self):
        self.assertEqual(cm('<script>x</script>'),
            '&lt;script&gt;x&lt;/script&gt;')
        self.assertEqual(cm('<iframe>x</iframe>'),
            '&lt;iframe&gt;x&lt;/iframe&gt;')

class FormTestCase(unittest.TestCase):
    def setUp(self):
        self.dirname = '_test_cgi_form'
        # set up and open a tracker
        self.instance = db_test_base.setupTracker(self.dirname)

        # open the database
        self.db = self.instance.open('admin')
        self.db.user.create(username='Chef', address='chef@bork.bork.bork',
            realname='Bork, Chef', roles='User')
        self.db.user.create(username='mary', address='mary@test.test',
            roles='User', realname='Contrary, Mary')

        test = self.instance.backend.Class(self.db, "test",
            string=hyperdb.String(), number=hyperdb.Number(),
            boolean=hyperdb.Boolean(), link=hyperdb.Link('test'),
            multilink=hyperdb.Multilink('test'), date=hyperdb.Date(),
            messages=hyperdb.Multilink('msg'), interval=hyperdb.Interval())

        # compile the labels re
        classes = '|'.join(self.db.classes.keys())
        self.FV_SPECIAL = re.compile(FormParser.FV_LABELS%classes,
            re.VERBOSE)

    def parseForm(self, form, classname='test', nodeid=None):
        cl = client.Client(self.instance, None, {'PATH_INFO':'/'},
            makeForm(form))
        cl.classname = classname
        cl.nodeid = nodeid
        cl.language = ('en',)
        cl.db = self.db
        return cl.parsePropsFromForm(create=1)

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    #
    # form label extraction
    #
    def tl(self, s, c, i, a, p):
        m = self.FV_SPECIAL.match(s)
        self.assertNotEqual(m, None)
        d = m.groupdict()
        self.assertEqual(d['classname'], c)
        self.assertEqual(d['id'], i)
        for action in 'required add remove link note file'.split():
            if a == action:
                self.assertNotEqual(d[action], None)
            else:
                self.assertEqual(d[action], None)
        self.assertEqual(d['propname'], p)

    def testLabelMatching(self):
        self.tl('<propname>', None, None, None, '<propname>')
        self.tl(':required', None, None, 'required', None)
        self.tl(':confirm:<propname>', None, None, 'confirm', '<propname>')
        self.tl(':add:<propname>', None, None, 'add', '<propname>')
        self.tl(':remove:<propname>', None, None, 'remove', '<propname>')
        self.tl(':link:<propname>', None, None, 'link', '<propname>')
        self.tl('test1:<prop>', 'test', '1', None, '<prop>')
        self.tl('test1:required', 'test', '1', 'required', None)
        self.tl('test1:add:<prop>', 'test', '1', 'add', '<prop>')
        self.tl('test1:remove:<prop>', 'test', '1', 'remove', '<prop>')
        self.tl('test1:link:<prop>', 'test', '1', 'link', '<prop>')
        self.tl('test1:confirm:<prop>', 'test', '1', 'confirm', '<prop>')
        self.tl('test-1:<prop>', 'test', '-1', None, '<prop>')
        self.tl('test-1:required', 'test', '-1', 'required', None)
        self.tl('test-1:add:<prop>', 'test', '-1', 'add', '<prop>')
        self.tl('test-1:remove:<prop>', 'test', '-1', 'remove', '<prop>')
        self.tl('test-1:link:<prop>', 'test', '-1', 'link', '<prop>')
        self.tl('test-1:confirm:<prop>', 'test', '-1', 'confirm', '<prop>')
        self.tl(':note', None, None, 'note', None)
        self.tl(':file', None, None, 'file', None)

    #
    # Empty form
    #
    def testNothing(self):
        self.assertEqual(self.parseForm({}), ({('test', None): {}}, []))

    def testNothingWithRequired(self):
        self.assertRaises(FormError, self.parseForm, {':required': 'string'})
        self.assertRaises(FormError, self.parseForm,
            {':required': 'title,status', 'status':'1'}, 'issue')
        self.assertRaises(FormError, self.parseForm,
            {':required': ['title','status'], 'status':'1'}, 'issue')
        self.assertRaises(FormError, self.parseForm,
            {':required': 'status', 'status':''}, 'issue')
        self.assertRaises(FormError, self.parseForm,
            {':required': 'nosy', 'nosy':''}, 'issue')
        self.assertRaises(FormError, self.parseForm,
            {':required': 'msg-1@content', 'msg-1@content':''}, 'issue')
        self.assertRaises(FormError, self.parseForm,
            {':required': 'msg-1@content'}, 'issue')

    #
    # Nonexistant edit
    #
    def testEditNonexistant(self):
        self.assertRaises(FormError, self.parseForm, {'boolean': ''},
            'test', '1')

    #
    # String
    #
    def testEmptyString(self):
        self.assertEqual(self.parseForm({'string': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'string': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'string': ['', '']})

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

    def testStringLinkId(self):
        self.db.status.set('1', name='2')
        self.db.status.set('2', name='1')
        issue = self.db.issue.create(title='i1-status1', status='1')
        self.assertEqual(self.db.issue.get(issue,'status'),'1')
        self.assertEqual(self.db.status.lookup('1'),'2')
        self.assertEqual(self.db.status.lookup('2'),'1')
        form = cgi.FieldStorage()
        cl = client.Client(self.instance, None, {'PATH_INFO':'/'}, form)
        cl.classname = 'issue'
        cl.nodeid = issue
        cl.db = self.db
        cl.language = ('en',)
        item = HTMLItem(cl, 'issue', issue)
        self.assertEqual(item.status.id, '1')
        self.assertEqual(item.status.name, '2')

    def testStringMultilinkId(self):
        id = self.db.keyword.create(name='2')
        self.assertEqual(id,'1')
        id = self.db.keyword.create(name='1')
        self.assertEqual(id,'2')
        issue = self.db.issue.create(title='i1-status1', keyword=['1'])
        self.assertEqual(self.db.issue.get(issue,'keyword'),['1'])
        self.assertEqual(self.db.keyword.lookup('1'),'2')
        self.assertEqual(self.db.keyword.lookup('2'),'1')
        form = cgi.FieldStorage()
        cl = client.Client(self.instance, None, {'PATH_INFO':'/'}, form)
        cl.classname = 'issue'
        cl.nodeid = issue
        cl.db = self.db
        cl.language = ('en',)
        cl.userid = '1'
        item = HTMLItem(cl, 'issue', issue)
        for keyword in item.keyword:
            self.assertEqual(keyword.id, '1')
            self.assertEqual(keyword.name, '2')

    def testFileUpload(self):
        file = FileUpload('foo', 'foo.txt')
        self.assertEqual(self.parseForm({'content': file}, 'file'),
            ({('file', None): {'content': 'foo', 'name': 'foo.txt',
            'type': 'text/plain'}}, []))

    def testEditFileClassAttributes(self):
        self.assertEqual(self.parseForm({'name': 'foo.txt',
                                         'type': 'application/octet-stream'},
                                        'file'),
                         ({('file', None): {'name': 'foo.txt',
                                            'type': 'application/octet-stream'}},[]))

    #
    # Link
    #
    def testEmptyLink(self):
        self.assertEqual(self.parseForm({'link': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'link': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'link': ['', '']})
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
        self.assertRaises(FormError, self.parseForm, {'link': 'frozzle'})
        self.assertRaises(FormError, self.parseForm, {'status': 'frozzle'},
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

    def testMixedMultilink(self):
        form = cgi.FieldStorage()
        form.list.append(cgi.MiniFieldStorage('nosy', '1,2'))
        form.list.append(cgi.MiniFieldStorage('nosy', '3'))
        cl = client.Client(self.instance, None, {'PATH_INFO':'/'}, form)
        cl.classname = 'issue'
        cl.nodeid = None
        cl.db = self.db
        cl.language = ('en',)
        self.assertEqual(cl.parsePropsFromForm(create=1),
            ({('issue', None): {'nosy': ['1','2', '3']}}, []))

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
        self.assertRaises(FormError, self.parseForm, {'nosy': 'frozzle'},
            'issue')
        self.assertRaises(FormError, self.parseForm, {'nosy': '1,frozzle'},
            'issue')
        self.assertRaises(FormError, self.parseForm, {'multilink': 'frozzle'})

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
        self.assertRaises(FormError, self.parseForm, {':remove:nosy': '4'},
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
        self.assertRaises(FormError, self.parseForm, {':remove:foo': '2'},
            'issue')
        self.assertRaises(FormError, self.parseForm, {':add:foo': '2'},
            'issue')

    #
    # Password
    #
    def testEmptyPassword(self):
        self.assertEqual(self.parseForm({'password': ''}, 'user'),
            ({('user', None): {}}, []))
        self.assertEqual(self.parseForm({'password': ''}, 'user'),
            ({('user', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'password': ['', '']},
            'user')
        self.assertRaises(FormError, self.parseForm, {'password': 'foo',
            ':confirm:password': ['', '']}, 'user')

    def testSetPassword(self):
        self.assertEqual(self.parseForm({'password': 'foo',
            ':confirm:password': 'foo'}, 'user'),
            ({('user', None): {'password': 'foo'}}, []))

    def testSetPasswordConfirmBad(self):
        self.assertRaises(FormError, self.parseForm, {'password': 'foo'},
            'user')
        self.assertRaises(FormError, self.parseForm, {'password': 'foo',
            ':confirm:password': 'bar'}, 'user')

    def testEmptyPasswordNotSet(self):
        nodeid = self.db.user.create(username='1',
            password=password.Password('foo'))
        self.assertEqual(self.parseForm({'password': ''}, 'user', nodeid),
            ({('user', nodeid): {}}, []))
        nodeid = self.db.user.create(username='2',
            password=password.Password('foo'))
        self.assertEqual(self.parseForm({'password': '',
            ':confirm:password': ''}, 'user', nodeid),
            ({('user', nodeid): {}}, []))

    #
    # Boolean
    #
    def testEmptyBoolean(self):
        self.assertEqual(self.parseForm({'boolean': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'boolean': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'boolean': ['', '']})

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

    def testRequiredBoolean(self):
        self.assertRaises(FormError, self.parseForm, {'boolean': '',
            ':required': 'boolean'})
        try:
            self.parseForm({'boolean': 'no', ':required': 'boolean'})
        except FormError:
            self.fail('boolean "no" raised "required missing"')

    #
    # Number
    #
    def testEmptyNumber(self):
        self.assertEqual(self.parseForm({'number': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'number': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'number': ['', '']})

    def testInvalidNumber(self):
        self.assertRaises(FormError, self.parseForm, {'number': 'hi, mum!'})

    def testSetNumber(self):
        self.assertEqual(self.parseForm({'number': '1'}),
            ({('test', None): {'number': 1}}, []))
        self.assertEqual(self.parseForm({'number': '0'}),
            ({('test', None): {'number': 0}}, []))
        self.assertEqual(self.parseForm({'number': '\n0\n'}),
            ({('test', None): {'number': 0}}, []))

    def testSetNumberReplaceOne(self):
        nodeid = self.db.test.create(number=1)
        self.assertEqual(self.parseForm({'number': '1'}, 'test', nodeid),
            ({('test', nodeid): {}}, []))
        self.assertEqual(self.parseForm({'number': '0'}, 'test', nodeid),
            ({('test', nodeid): {'number': 0}}, []))

    def testSetNumberReplaceZero(self):
        nodeid = self.db.test.create(number=0)
        self.assertEqual(self.parseForm({'number': '0'}, 'test', nodeid),
            ({('test', nodeid): {}}, []))

    def testSetNumberReplaceNone(self):
        nodeid = self.db.test.create()
        self.assertEqual(self.parseForm({'number': '0'}, 'test', nodeid),
            ({('test', nodeid): {'number': 0}}, []))
        self.assertEqual(self.parseForm({'number': '1'}, 'test', nodeid),
            ({('test', nodeid): {'number': 1}}, []))

    def testEmptyNumberSet(self):
        nodeid = self.db.test.create(number=0)
        self.assertEqual(self.parseForm({'number': ''}, 'test', nodeid),
            ({('test', nodeid): {'number': None}}, []))
        nodeid = self.db.test.create(number=1)
        self.assertEqual(self.parseForm({'number': ' '}, 'test', nodeid),
            ({('test', nodeid): {'number': None}}, []))

    def testRequiredNumber(self):
        self.assertRaises(FormError, self.parseForm, {'number': '',
            ':required': 'number'})
        try:
            self.parseForm({'number': '0', ':required': 'number'})
        except FormError:
            self.fail('number "no" raised "required missing"')

    #
    # Date
    #
    def testEmptyDate(self):
        self.assertEqual(self.parseForm({'date': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'date': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'date': ['', '']})

    def testInvalidDate(self):
        self.assertRaises(FormError, self.parseForm, {'date': '12'})

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
            ({('test', None): {'string': 'a'},
              ('issue', '-1'): {'title': 'b'}
             }, []))

    def testMultipleExistingContext(self):
        nodeid = self.db.test.create()
        self.assertEqual(self.parseForm({'string': 'a', 'issue-1@title': 'b'},
            'test', nodeid),({('test', nodeid): {'string': 'a'},
            ('issue', '-1'): {'title': 'b'}}, []))

    def testLinking(self):
        self.assertEqual(self.parseForm({
            'string': 'a',
            'issue-1@add@nosy': '1',
            'issue-2@link@superseder': 'issue-1',
            }),
            ({('test', None): {'string': 'a'},
              ('issue', '-1'): {'nosy': ['1']},
             },
             [('issue', '-2', 'superseder', [('issue', '-1')])
             ]
            )
        )

    def testMessages(self):
        self.assertEqual(self.parseForm({
            'msg-1@content': 'asdf',
            'msg-2@content': 'qwer',
            '@link@messages': 'msg-1, msg-2'}),
            ({('test', None): {},
              ('msg', '-2'): {'content': 'qwer'},
              ('msg', '-1'): {'content': 'asdf'}},
             [('test', None, 'messages', [('msg', '-1'), ('msg', '-2')])]
            )
        )

    def testLinkBadDesignator(self):
        self.assertRaises(FormError, self.parseForm,
            {'test-1@link@link': 'blah'})
        self.assertRaises(FormError, self.parseForm,
            {'test-1@link@link': 'issue'})

    def testLinkNotLink(self):
        self.assertRaises(FormError, self.parseForm,
            {'test-1@link@boolean': 'issue-1'})
        self.assertRaises(FormError, self.parseForm,
            {'test-1@link@string': 'issue-1'})

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

    #
    # SECURITY
    #
    # XXX test all default permissions
    def _make_client(self, form, classname='user', nodeid='2', userid='2'):
        cl = client.Client(self.instance, None, {'PATH_INFO':'/'},
            makeForm(form))
        cl.classname = 'user'
        cl.nodeid = '1'
        cl.db = self.db
        cl.userid = '2'
        cl.language = ('en',)
        return cl

    def testClassPermission(self):
        cl = self._make_client(dict(username='bob'))
        self.failUnlessRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        cl.nodeid = '1'
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)

    def testCheckAndPropertyPermission(self):
        self.db.security.permissions = {}
        def own_record(db, userid, itemid): return userid == itemid
        p = self.db.security.addPermission(name='Edit', klass='user',
            check=own_record, properties=("password", ))
        self.db.security.addPermissionToRole('User', p)

        cl = self._make_client(dict(username='bob'))
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        cl = self._make_client({'password':'bob', '@confirm@password':'bob'})
        self.failUnlessRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(FormTestCase))
    suite.addTest(unittest.makeSuite(MessageTestCase))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: set filetype=python sts=4 sw=4 et si :
