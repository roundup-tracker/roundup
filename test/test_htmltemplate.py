#
# Copyright (c) 2001 Richard Jones
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# $Id: test_htmltemplate.py,v 1.21 2002-09-10 00:19:54 richard Exp $ 

import unittest, cgi, time, os, shutil

from roundup import date, password
from roundup.htmltemplate import IndexTemplate, ItemTemplate
from roundup import template_funcs
tf = template_funcs
from roundup.i18n import _
from roundup.hyperdb import String, Password, Date, Interval, Link, \
    Multilink, Boolean, Number

class TestClass:
    def get(self, nodeid, attribute, default=None):
        if attribute == 'string':
            return 'Node %s: I am a string'%nodeid
        elif attribute == 'filename':
            return 'file.foo'
        elif attribute == 'date':
            return date.Date('2000-01-01')
        elif attribute == 'boolean':
            return 0
        elif attribute == 'number':
            return 1234
        elif attribute == 'reldate':
            return date.Date() + date.Interval('- 2y 1m')
        elif attribute == 'interval':
            return date.Interval('-3d')
        elif attribute == 'link':
            return '1'
        elif attribute == 'multilink':
            return ['1', '2']
        elif attribute == 'password':
            return password.Password('sekrit')
        elif attribute == 'key':
            return 'the key'+nodeid
        elif attribute == 'html':
            return '<html>hello, I am HTML</html>'
        elif attribute == 'multiline':
            return 'hello\nworld'
        elif attribute == 'email':
            return 'test@foo.domain.example'
    def list(self):
        return ['1', '2']
    def filter(self, search_matches, filterspec, sort, group):
        return ['1', '2']
    def getprops(self):
        return {'string': String(), 'date': Date(), 'interval': Interval(),
            'link': Link('other'), 'multilink': Multilink('other'),
            'password': Password(), 'html': String(), 'key': String(),
            'novalue': String(), 'filename': String(), 'multiline': String(),
            'reldate': Date(), 'email': String(), 'boolean': Boolean(),
            'number': Number()}
    def labelprop(self, default_to_id=0):
        return 'key'

class TestDatabase:
    classes = {'other': TestClass()}
    def getclass(self, name):
        return TestClass()
    def __getattr(self, name):
        return Class()

class TestClient:
    def __init__(self):
        self.db = None
        self.form = None
        self.write = None

class FunctionCase(unittest.TestCase):
    def setUp(self):
        ''' Set up the harness for calling the individual tests
        '''
        client = TestClient()
        client.db = TestDatabase()
        cl = TestClass()
        self.args = (client, 'test_class', cl, cl.getprops(), '1', None) 

    def call(self, func, *args, **kws):
        args = self.args + args
        return func(*args, **kws)
        
#    def do_plain(self, property, escape=0):
    def testPlain_string(self):
        s = 'Node 1: I am a string'
        self.assertEqual(self.call(tf.do_plain, 'string'), s)

    def testPlain_password(self):
        self.assertEqual(self.call(tf.do_plain, 'password'), '*encrypted*')

    def testPlain_html(self):
        s = '<html>hello, I am HTML</html>'
        self.assertEqual(self.call(tf.do_plain, 'html', escape=0), s)
        s = cgi.escape(s)
        self.assertEqual(self.call(tf.do_plain, 'html', escape=1), s)

    def testPlain_date(self):
        self.assertEqual(self.call(tf.do_plain, 'date'), '2000-01-01.00:00:00')

    def testPlain_interval(self):
        self.assertEqual(self.call(tf.do_plain, 'interval'), '- 3d')

    def testPlain_link(self):
        self.assertEqual(self.call(tf.do_plain, 'link'), 'the key1')

    def testPlain_multilink(self):
        self.assertEqual(self.call(tf.do_plain, 'multilink'), 'the key1, the key2')

    def testPlain_boolean(self):
        self.assertEqual(self.call(tf.do_plain, 'boolean'), 'No')

    def testPlain_number(self):
        self.assertEqual(self.call(tf.do_plain,'number'), '1234')

#    def do_field(self, property, size=None, showid=0):
    def testField_string(self):
        self.assertEqual(self.call(tf.do_field, 'string'),
            '<input name="string" value="Node 1: I am a string" size="30">')
        self.assertEqual(self.call(tf.do_field, 'string', size=10),
            '<input name="string" value="Node 1: I am a string" size="10">')

    def testField_password(self):
        self.assertEqual(self.call(tf.do_field, 'password'),
            '<input type="password" name="password" size="30">')
        self.assertEqual(self.call(tf.do_field,'password', size=10),
            '<input type="password" name="password" size="10">')

    def testField_html(self):
        self.assertEqual(self.call(tf.do_field, 'html'), '<input name="html" '
            'value="&lt;html&gt;hello, I am HTML&lt;/html&gt;" size="30">')
        self.assertEqual(self.call(tf.do_field, 'html', size=10),
            '<input name="html" value="&lt;html&gt;hello, I am '
            'HTML&lt;/html&gt;" size="10">')

    def testField_date(self):
        self.assertEqual(self.call(tf.do_field, 'date'),
            '<input name="date" value="2000-01-01.00:00:00" size="30">')
        self.assertEqual(self.call(tf.do_field, 'date', size=10),
            '<input name="date" value="2000-01-01.00:00:00" size="10">')

    def testField_interval(self):
        self.assertEqual(self.call(tf.do_field,'interval'),
            '<input name="interval" value="- 3d" size="30">')
        self.assertEqual(self.call(tf.do_field, 'interval', size=10),
            '<input name="interval" value="- 3d" size="10">')

    def testField_link(self):
        self.assertEqual(self.call(tf.do_field, 'link'), '''<select name="link">
<option value="-1">- no selection -</option>
<option selected value="1">the key1</option>
<option value="2">the key2</option>
</select>''')

    def testField_multilink(self):
        self.assertEqual(self.call(tf.do_field,'multilink'),
            '<input name="multilink" size="30" value="the key1,the key2">')
        self.assertEqual(self.call(tf.do_field, 'multilink', size=10),
            '<input name="multilink" size="10" value="the key1,the key2">')

    def testField_boolean(self):
        self.assertEqual(self.call(tf.do_field, 'boolean'),
            '<input type="radio" name="boolean" value="yes" >Yes<input type="radio" name="boolean" value="no" checked>No')

    def testField_number(self):
        self.assertEqual(self.call(tf.do_field, 'number'),
            '<input name="number" value="1234" size="30">')
        self.assertEqual(self.call(tf.do_field, 'number', size=10),
            '<input name="number" value="1234" size="10">')

#    def do_multiline(self, property, rows=5, cols=40)
    def testMultiline_string(self):
        self.assertEqual(self.call(tf.do_multiline, 'multiline'),
            '<textarea name="multiline" rows="5" cols="40">'
            'hello\nworld</textarea>')
        self.assertEqual(self.call(tf.do_multiline, 'multiline', rows=10),
            '<textarea name="multiline" rows="10" cols="40">'
            'hello\nworld</textarea>')
        self.assertEqual(self.call(tf.do_multiline, 'multiline', cols=10),
            '<textarea name="multiline" rows="5" cols="10">'
            'hello\nworld</textarea>')

    def testMultiline_nonstring(self):
        s = _('[Multiline: not a string]')
        self.assertEqual(self.call(tf.do_multiline, 'date'), s)
        self.assertEqual(self.call(tf.do_multiline, 'interval'), s)
        self.assertEqual(self.call(tf.do_multiline, 'password'), s)
        self.assertEqual(self.call(tf.do_multiline, 'link'), s)
        self.assertEqual(self.call(tf.do_multiline, 'multilink'), s)
        self.assertEqual(self.call(tf.do_multiline, 'boolean'), s)
        self.assertEqual(self.call(tf.do_multiline, 'number'), s)

#    def do_menu(self, property, size=None, height=None, showid=0):
    def testMenu_nonlinks(self):
        s = _('[Menu: not a link]')
        self.assertEqual(self.call(tf.do_menu, 'string'), s)
        self.assertEqual(self.call(tf.do_menu, 'date'), s)
        self.assertEqual(self.call(tf.do_menu, 'interval'), s)
        self.assertEqual(self.call(tf.do_menu, 'password'), s)
        self.assertEqual(self.call(tf.do_menu, 'boolean'), s)
        self.assertEqual(self.call(tf.do_menu, 'number'), s)

    def testMenu_link(self):
        self.assertEqual(self.call(tf.do_menu, 'link'), '''<select name="link">
<option value="-1">- no selection -</option>
<option selected value="1">the key1</option>
<option value="2">the key2</option>
</select>''')
        self.assertEqual(self.call(tf.do_menu, 'link', size=6),
            '''<select name="link">
<option value="-1">- no selection -</option>
<option selected value="1">the...</option>
<option value="2">the...</option>
</select>''')
        self.assertEqual(self.call(tf.do_menu, 'link', showid=1),
            '''<select name="link">
<option value="-1">- no selection -</option>
<option selected value="1">other1: the key1</option>
<option value="2">other2: the key2</option>
</select>''')

    def testMenu_multilink(self):
        self.assertEqual(self.call(tf.do_menu, 'multilink', height=10),
            '''<select multiple name="multilink" size="10">
<option selected value="1">the key1</option>
<option selected value="2">the key2</option>
</select>''')
        self.assertEqual(self.call(tf.do_menu, 'multilink', size=6, height=10),
            '''<select multiple name="multilink" size="10">
<option selected value="1">the...</option>
<option selected value="2">the...</option>
</select>''')
        self.assertEqual(self.call(tf.do_menu, 'multilink', showid=1),
            '''<select multiple name="multilink" size="2">
<option selected value="1">other1: the key1</option>
<option selected value="2">other2: the key2</option>
</select>''')

#    def do_link(self, property=None, is_download=0):
    def testLink_novalue(self):
        self.assertEqual(self.call(tf.do_link, 'novalue'),
            _('[no %(propname)s]')%{'propname':'novalue'.capitalize()})

    def testLink_string(self):
        self.assertEqual(self.call(tf.do_link, 'string'),
            '<a href="test_class1">Node 1: I am a string</a>')

    def testLink_file(self):
        self.assertEqual(self.call(tf.do_link, 'filename', is_download=1),
            '<a href="test_class1/file.foo">file.foo</a>')

    def testLink_date(self):
        self.assertEqual(self.call(tf.do_link, 'date'),
            '<a href="test_class1">2000-01-01.00:00:00</a>')

    def testLink_interval(self):
        self.assertEqual(self.call(tf.do_link, 'interval'),
            '<a href="test_class1">- 3d</a>')

    def testLink_link(self):
        self.assertEqual(self.call(tf.do_link, 'link'),
            '<a href="other1">the key1</a>')

    def testLink_link_id(self):
        self.assertEqual(self.call(tf.do_link, 'link', showid=1),
            '<a href="other1" title="the key1">1</a>')

    def testLink_multilink(self):
        self.assertEqual(self.call(tf.do_link, 'multilink'),
            '<a href="other1">the key1</a>, <a href="other2">the key2</a>')

    def testLink_multilink_id(self):
        self.assertEqual(self.call(tf.do_link, 'multilink', showid=1),
            '<a href="other1" title="the key1">1</a>, <a href="other2" title="the key2">2</a>')

    def testLink_boolean(self):
        self.assertEqual(self.call(tf.do_link, 'boolean'),
            '<a href="test_class1">No</a>')

    def testLink_number(self):
        self.assertEqual(self.call(tf.do_link, 'number'),
            '<a href="test_class1">1234</a>')

#    def do_count(self, property, **args):
    def testCount_nonlinks(self):
        s = _('[Count: not a Multilink]')
        self.assertEqual(self.call(tf.do_count, 'string'), s)
        self.assertEqual(self.call(tf.do_count, 'date'), s)
        self.assertEqual(self.call(tf.do_count, 'interval'), s)
        self.assertEqual(self.call(tf.do_count, 'password'), s)
        self.assertEqual(self.call(tf.do_count, 'link'), s)
        self.assertEqual(self.call(tf.do_count, 'boolean'), s)
        self.assertEqual(self.call(tf.do_count, 'number'), s)

    def testCount_multilink(self):
        self.assertEqual(self.call(tf.do_count, 'multilink'), '2')

#    def do_reldate(self, property, pretty=0):
    def testReldate_nondate(self):
        s = _('[Reldate: not a Date]')
        self.assertEqual(self.call(tf.do_reldate, 'string'), s)
        self.assertEqual(self.call(tf.do_reldate, 'interval'), s)
        self.assertEqual(self.call(tf.do_reldate, 'password'), s)
        self.assertEqual(self.call(tf.do_reldate, 'link'), s)
        self.assertEqual(self.call(tf.do_reldate, 'multilink'), s)
        self.assertEqual(self.call(tf.do_reldate, 'boolean'), s)
        self.assertEqual(self.call(tf.do_reldate, 'number'), s)

    def testReldate_date(self):
        self.assertEqual(self.call(tf.do_reldate, 'reldate'), '- 2y 1m')
        interval = date.Interval('- 2y 1m')
        self.assertEqual(self.call(tf.do_reldate, 'reldate', pretty=1),
            interval.pretty())

#    def do_download(self, property):
    def testDownload_novalue(self):
        self.assertEqual(self.call(tf.do_download, 'novalue'),
            _('[no %(propname)s]')%{'propname':'novalue'.capitalize()})

    def testDownload_string(self):
        self.assertEqual(self.call(tf.do_download, 'string'),
            '<a href="test_class1/Node 1: I am a string">Node 1: '
            'I am a string</a>')

    def testDownload_file(self):
        self.assertEqual(self.call(tf.do_download, 'filename', is_download=1),
            '<a href="test_class1/file.foo">file.foo</a>')

    def testDownload_date(self):
        self.assertEqual(self.call(tf.do_download, 'date'),
            '<a href="test_class1/2000-01-01.00:00:00">2000-01-01.00:00:00</a>')

    def testDownload_interval(self):
        self.assertEqual(self.call(tf.do_download, 'interval'),
            '<a href="test_class1/- 3d">- 3d</a>')

    def testDownload_link(self):
        self.assertEqual(self.call(tf.do_download, 'link'),
            '<a href="other1/the key1">the key1</a>')

    def testDownload_multilink(self):
        self.assertEqual(self.call(tf.do_download, 'multilink'),
            '<a href="other1/the key1">the key1</a>, '
            '<a href="other2/the key2">the key2</a>')

    def testDownload_boolean(self):
        self.assertEqual(self.call(tf.do_download, 'boolean'),
            '<a href="test_class1/No">No</a>')

    def testDownload_number(self):
        self.assertEqual(self.call(tf.do_download, 'number'),
            '<a href="test_class1/1234">1234</a>')

#    def do_checklist(self, property, reverse=0):
    def testChecklist_nonlinks(self):
        s = _('[Checklist: not a link]')
        self.assertEqual(self.call(tf.do_checklist, 'string'), s)
        self.assertEqual(self.call(tf.do_checklist, 'date'), s)
        self.assertEqual(self.call(tf.do_checklist, 'interval'), s)
        self.assertEqual(self.call(tf.do_checklist, 'password'), s)
        self.assertEqual(self.call(tf.do_checklist, 'boolean'), s)
        self.assertEqual(self.call(tf.do_checklist, 'number'), s)

    def testChecklstk_link(self):
        self.assertEqual(self.call(tf.do_checklist, 'link'),
            '''the key1:<input type="checkbox" checked name="link" value="the key1">
the key2:<input type="checkbox"  name="link" value="the key2">
[unselected]:<input type="checkbox"  name="link" value="-1">''')

    def testChecklink_multilink(self):
        self.assertEqual(self.call(tf.do_checklist, 'multilink'),
            '''the key1:<input type="checkbox" checked name="multilink" value="the key1">
the key2:<input type="checkbox" checked name="multilink" value="the key2">''')

#    def do_note(self, rows=5, cols=80):
    def testNote(self):
        self.assertEqual(self.call(tf.do_note), '<textarea name="__note" '
            'wrap="hard" rows=5 cols=80></textarea>')

#    def do_list(self, property, reverse=0):
    def testList_nonlinks(self):
        s = _('[List: not a Multilink]')
        self.assertEqual(self.call(tf.do_list, 'string'), s)
        self.assertEqual(self.call(tf.do_list, 'date'), s)
        self.assertEqual(self.call(tf.do_list, 'interval'), s)
        self.assertEqual(self.call(tf.do_list, 'password'), s)
        self.assertEqual(self.call(tf.do_list, 'link'), s)
        self.assertEqual(self.call(tf.do_list, 'boolean'), s)
        self.assertEqual(self.call(tf.do_list, 'number'), s)

    def testList_multilink(self):
        # TODO: test this (needs to have lots and lots of support!
        #self.assertEqual(self.tf.do_list('multilink'),'')
        pass

    def testClasshelp(self):
        self.assertEqual(self.call(tf.do_classhelp, 'theclass', 'prop1,prop2'),
            '<a href="javascript:help_window(\'classhelp?classname=theclass'
            '&properties=prop1,prop2\', \'400\', \'400\')"><b>(?)</b></a>')

#    def do_email(self, property, rows=5, cols=40)
    def testEmail_string(self):
        self.assertEqual(self.call(tf.do_email, 'email'), 'test at foo domain example')

    def testEmail_nonstring(self):
        s = _('[Email: not a string]')
        self.assertEqual(self.call(tf.do_email, 'date'), s)
        self.assertEqual(self.call(tf.do_email, 'interval'), s)
        self.assertEqual(self.call(tf.do_email, 'password'), s)
        self.assertEqual(self.call(tf.do_email, 'link'), s)
        self.assertEqual(self.call(tf.do_email, 'multilink'), s)
        self.assertEqual(self.call(tf.do_email, 'boolean'), s)
        self.assertEqual(self.call(tf.do_email, 'number'), s)


from test_db import setupSchema, MyTestCase, config

class Client:
    user = 'admin'

class IndexTemplateCase(unittest.TestCase):
    def setUp(self):
        from roundup.backends import anydbm
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = anydbm.Database(config, 'test')
        setupSchema(self.db, 1, anydbm)

        client = Client()
        client.db = self.db
        client.instance = None
        self.tf = tf = IndexTemplate(client, '', 'issue')
        tf.props = ['title']

        # admin user
        self.db.user.create(username="admin", roles='Admin')
        self.db.user.create(username="anonymous", roles='User')

    def testBasic(self):
        self.assertEqual(self.tf.execute_template('hello'), 'hello')

    def testValue(self):
        self.tf.nodeid = self.db.issue.create(title="spam", status='1')
        self.assertEqual(self.tf.execute_template('<display call="plain(\'title\')">'), 'spam')

    def testColumnSelection(self):
        self.tf.nodeid = self.db.issue.create(title="spam", status='1')
        self.assertEqual(self.tf.execute_template('<property name="title">'
            '<display call="plain(\'title\')"></property>'
            '<property name="bar">hello</property>'), 'spam')
        self.tf.props = ['bar']
        self.assertEqual(self.tf.execute_template('<property name="title">'
            '<display call="plain(\'title\')"></property>'
            '<property name="bar">hello</property>'), 'hello')

    def testSecurityPass(self):
        self.assertEqual(self.tf.execute_template(
            '<require permission="Edit">hello<else>foo</require>'), 'hello')

    def testSecurityPassValue(self):
        self.tf.nodeid = self.db.issue.create(title="spam", status='1')
        self.assertEqual(self.tf.execute_template(
            '<require permission="Edit">'
            '<display call="plain(\'title\')">'
            '<else>not allowed</require>'), 'spam')

    def testSecurityFail(self):
        self.tf.client.user = 'anonymous'
        self.assertEqual(self.tf.execute_template(
            '<require permission="Edit">hello<else>foo</require>'), 'foo')

    def testSecurityFailValue(self):
        self.tf.nodeid = self.db.issue.create(title="spam", status='1')
        self.tf.client.user = 'anonymous'
        self.assertEqual(self.tf.execute_template(
            '<require permission="Edit">allowed<else>'
            '<display call="plain(\'title\')"></require>'), 'spam')

    def tearDown(self):
        if os.path.exists('_test_dir'):
            shutil.rmtree('_test_dir')


class ItemTemplateCase(unittest.TestCase):
    def setUp(self):
        ''' Set up the harness for calling the individual tests
        '''
        from roundup.backends import anydbm
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = anydbm.Database(config, 'test')
        setupSchema(self.db, 1, anydbm)

        client = Client()
        client.db = self.db
        client.instance = None
        self.tf = tf = IndexTemplate(client, '', 'issue')
        tf.nodeid = self.db.issue.create(title="spam", status='1')

        # admin user
        self.db.user.create(username="admin", roles='Admin')
        self.db.user.create(username="anonymous", roles='User')

    def testBasic(self):
        self.assertEqual(self.tf.execute_template('hello'), 'hello')

    def testValue(self):
        self.assertEqual(self.tf.execute_template('<display call="plain(\'title\')">'), 'spam')

    def testSecurityPass(self):
        self.assertEqual(self.tf.execute_template(
            '<require permission="Edit">hello<else>foo</require>'), 'hello')

    def testSecurityPassValue(self):
        self.assertEqual(self.tf.execute_template(
            '<require permission="Edit">'
            '<display call="plain(\'title\')">'
            '<else>not allowed</require>'), 'spam')

    def testSecurityFail(self):
        self.tf.client.user = 'anonymous'
        self.assertEqual(self.tf.execute_template(
            '<require permission="Edit">hello<else>foo</require>'), 'foo')

    def testSecurityFailValue(self):
        self.tf.client.user = 'anonymous'
        self.assertEqual(self.tf.execute_template(
            '<require permission="Edit">allowed<else>'
            '<display call="plain(\'title\')"></require>'), 'spam')

    def tearDown(self):
        if os.path.exists('_test_dir'):
            shutil.rmtree('_test_dir')

def suite():
    return unittest.TestSuite([
        unittest.makeSuite(FunctionCase, 'test'),
        #unittest.makeSuite(IndexTemplateCase, 'test'),
        #unittest.makeSuite(ItemTemplateCase, 'test'),
    ])


# vim: set filetype=python ts=4 sw=4 et si
