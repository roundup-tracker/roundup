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
# $Id: test_htmltemplate.py,v 1.8 2002-02-06 03:47:16 richard Exp $ 

import unittest, cgi, time

from roundup import date, password
from roundup.htmltemplate import TemplateFunctions
from roundup.i18n import _
from roundup.hyperdb import String, Password, Date, Interval, Link, Multilink

class Class:
    def get(self, nodeid, attribute, default=None):
        if attribute == 'string':
            return 'Node %s: I am a string'%nodeid
        elif attribute == 'filename':
            return 'file.foo'
        elif attribute == 'date':
            return date.Date('2000-01-01')
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
    def list(self):
        return ['1', '2']
    def getprops(self):
        return {'string': String(), 'date': Date(), 'interval': Interval(),
            'link': Link('other'), 'multilink': Multilink('other'),
            'password': Password(), 'html': String(), 'key': String(),
            'novalue': String(), 'filename': String()}
    def labelprop(self):
        return 'key'

class Database:
    classes = {'other': Class()}
    def getclass(self, name):
        return Class()
    def __getattr(self, name):
        return Class()

class Client:
    write = None

class NodeCase(unittest.TestCase):
    def setUp(self):
        ''' Set up the harness for calling the individual tests
        '''
        self.tf = tf = TemplateFunctions()
        tf.nodeid = '1'
        tf.cl = Class()
        tf.classname = 'test_class'
        tf.properties = tf.cl.getprops()
        tf.db = Database()

#    def do_plain(self, property, escape=0):
    def testPlain_string(self):
        s = 'Node 1: I am a string'
        self.assertEqual(self.tf.do_plain('string'), s)

    def testPlain_password(self):
        self.assertEqual(self.tf.do_plain('password'), '*encrypted*')

    def testPlain_html(self):
        s = '<html>hello, I am HTML</html>'
        self.assertEqual(self.tf.do_plain('html', escape=0), s)
        s = cgi.escape(s)
        self.assertEqual(self.tf.do_plain('html', escape=1), s)

    def testPlain_date(self):
        self.assertEqual(self.tf.do_plain('date'), '2000-01-01.00:00:00')

    def testPlain_interval(self):
        self.assertEqual(self.tf.do_plain('interval'), '- 3d')

    def testPlain_link(self):
        self.assertEqual(self.tf.do_plain('link'), 'the key1')

    def testPlain_multilink(self):
        self.assertEqual(self.tf.do_plain('multilink'), '1, 2')


#    def do_field(self, property, size=None, showid=0):
    def testField_string(self):
        self.assertEqual(self.tf.do_field('string'),
            '<input name="string" value="Node 1: I am a string" size="30">')
        self.assertEqual(self.tf.do_field('string', size=10),
            '<input name="string" value="Node 1: I am a string" size="10">')

    def testField_password(self):
        self.assertEqual(self.tf.do_field('password'),
            '<input type="password" name="password" size="30">')
        self.assertEqual(self.tf.do_field('password', size=10),
            '<input type="password" name="password" size="10">')

    def testField_html(self):
        self.assertEqual(self.tf.do_field('html'), '<input name="html" '
            'value="&lt;html&gt;hello, I am HTML&lt;/html&gt;" size="30">')
        self.assertEqual(self.tf.do_field('html', size=10),
            '<input name="html" value="&lt;html&gt;hello, I am '
            'HTML&lt;/html&gt;" size="10">')

    def testField_date(self):
        self.assertEqual(self.tf.do_field('date'),
            '<input name="date" value="2000-01-01.00:00:00" size="30">')
        self.assertEqual(self.tf.do_field('date', size=10),
            '<input name="date" value="2000-01-01.00:00:00" size="10">')

    def testField_interval(self):
        self.assertEqual(self.tf.do_field('interval'),
            '<input name="interval" value="- 3d" size="30">')
        self.assertEqual(self.tf.do_field('interval', size=10),
            '<input name="interval" value="- 3d" size="10">')

    def testField_link(self):
        self.assertEqual(self.tf.do_field('link'), '''<select name="link">
<option value="-1">- no selection -</option>
<option selected value="1">the key1</option>
<option value="2">the key2</option>
</select>''')

    def testField_multilink(self):
        self.assertEqual(self.tf.do_field('multilink'),
            '<input name="multilink" size="30" value="the key1,the key2">')
        self.assertEqual(self.tf.do_field('multilink', size=10),
            '<input name="multilink" size="10" value="the key1,the key2">')

#    def do_menu(self, property, size=None, height=None, showid=0):
    def testMenu_nonlinks(self):
    	s = _('[Menu: not a link]')
        self.assertEqual(self.tf.do_menu('string'), s)
        self.assertEqual(self.tf.do_menu('date'), s)
        self.assertEqual(self.tf.do_menu('interval'), s)
        self.assertEqual(self.tf.do_menu('password'), s)

    def testMenu_link(self):
        self.assertEqual(self.tf.do_menu('link'), '''<select name="link">
<option value="-1">- no selection -</option>
<option selected value="1">the key1</option>
<option value="2">the key2</option>
</select>''')
        self.assertEqual(self.tf.do_menu('link', size=6),
            '''<select name="link">
<option value="-1">- no selection -</option>
<option selected value="1">the...</option>
<option value="2">the...</option>
</select>''')
        self.assertEqual(self.tf.do_menu('link', showid=1),
            '''<select name="link">
<option value="-1">- no selection -</option>
<option selected value="1">other1: the key1</option>
<option value="2">other2: the key2</option>
</select>''')

    def testMenu_multilink(self):
        self.assertEqual(self.tf.do_menu('multilink', height=10),
            '''<select multiple name="multilink" size="10">
<option selected value="1">the key1</option>
<option selected value="2">the key2</option>
</select>''')
        self.assertEqual(self.tf.do_menu('multilink', size=6, height=10),
            '''<select multiple name="multilink" size="10">
<option selected value="1">the...</option>
<option selected value="2">the...</option>
</select>''')
        self.assertEqual(self.tf.do_menu('multilink', showid=1),
            '''<select multiple name="multilink" size="2">
<option selected value="1">other1: the key1</option>
<option selected value="2">other2: the key2</option>
</select>''')

#    def do_link(self, property=None, is_download=0):
    def testLink_novalue(self):
        self.assertEqual(self.tf.do_link('novalue'),
            _('[no %(propname)s]')%{'propname':'novalue'.capitalize()})

    def testLink_string(self):
        self.assertEqual(self.tf.do_link('string'),
            '<a href="test_class1">Node 1: I am a string</a>')

    def testLink_file(self):
        self.assertEqual(self.tf.do_link('filename', is_download=1),
            '<a href="test_class1/file.foo">file.foo</a>')

    def testLink_date(self):
        self.assertEqual(self.tf.do_link('date'),
            '<a href="test_class1">2000-01-01.00:00:00</a>')

    def testLink_interval(self):
        self.assertEqual(self.tf.do_link('interval'),
            '<a href="test_class1">- 3d</a>')

    def testLink_link(self):
        self.assertEqual(self.tf.do_link('link'),
            '<a href="other1">the key1</a>')

    def testLink_multilink(self):
        self.assertEqual(self.tf.do_link('multilink'),
            '<a href="other1">the key1</a>, <a href="other2">the key2</a>')

#    def do_count(self, property, **args):
    def testCount_nonlinks(self):
        s = _('[Count: not a Multilink]')
        self.assertEqual(self.tf.do_count('string'), s)
        self.assertEqual(self.tf.do_count('date'), s)
        self.assertEqual(self.tf.do_count('interval'), s)
        self.assertEqual(self.tf.do_count('password'), s)
        self.assertEqual(self.tf.do_count('link'), s)

    def testCount_multilink(self):
        self.assertEqual(self.tf.do_count('multilink'), '2')

#    def do_reldate(self, property, pretty=0):
    def testReldate_nondate(self):
        s = _('[Reldate: not a Date]')
        self.assertEqual(self.tf.do_reldate('string'), s)
        self.assertEqual(self.tf.do_reldate('interval'), s)
        self.assertEqual(self.tf.do_reldate('password'), s)
        self.assertEqual(self.tf.do_reldate('link'), s)
        self.assertEqual(self.tf.do_reldate('multilink'), s)

    def testReldate_date(self):
        self.assertEqual(self.tf.do_reldate('date'), '- 2y 1m')
	date = self.tf.cl.get('1', 'date')
        self.assertEqual(self.tf.do_reldate('date', pretty=1), date.pretty())

#    def do_download(self, property):
    def testDownload_novalue(self):
        self.assertEqual(self.tf.do_download('novalue'),
            _('[no %(propname)s]')%{'propname':'novalue'.capitalize()})

    def testDownload_string(self):
        self.assertEqual(self.tf.do_download('string'),
            '<a href="test_class1/Node 1: I am a string">Node 1: '
	    'I am a string</a>')

    def testDownload_file(self):
        self.assertEqual(self.tf.do_download('filename', is_download=1),
            '<a href="test_class1/file.foo">file.foo</a>')

    def testDownload_date(self):
        self.assertEqual(self.tf.do_download('date'),
            '<a href="test_class1/2000-01-01.00:00:00">2000-01-01.00:00:00</a>')

    def testDownload_interval(self):
        self.assertEqual(self.tf.do_download('interval'),
            '<a href="test_class1/- 3d">- 3d</a>')

    def testDownload_link(self):
        self.assertEqual(self.tf.do_download('link'),
            '<a href="other1/the key1">the key1</a>')

    def testDownload_multilink(self):
        self.assertEqual(self.tf.do_download('multilink'),
            '<a href="other1/the key1">the key1</a>, '
	    '<a href="other2/the key2">the key2</a>')

#    def do_checklist(self, property, reverse=0):
    def testChecklink_nonlinks(self):
        s = _('[Checklist: not a link]')
        self.assertEqual(self.tf.do_checklist('string'), s)
        self.assertEqual(self.tf.do_checklist('date'), s)
        self.assertEqual(self.tf.do_checklist('interval'), s)
        self.assertEqual(self.tf.do_checklist('password'), s)

    def testChecklink_link(self):
        self.assertEqual(self.tf.do_checklist('link'),
            '''the key1:<input type="checkbox" checked name="link" value="the key1">
the key2:<input type="checkbox"  name="link" value="the key2">
[unselected]:<input type="checkbox"  name="link" value="-1">''')

    def testChecklink_multilink(self):
        self.assertEqual(self.tf.do_checklist('multilink'),
            '''the key1:<input type="checkbox" checked name="multilink" value="the key1">
the key2:<input type="checkbox" checked name="multilink" value="the key2">''')

#    def do_note(self, rows=5, cols=80):
    def testNote(self):
        self.assertEqual(self.tf.do_note(), '<textarea name="__note" '
            'wrap="hard" rows=5 cols=80></textarea>')

#    def do_list(self, property, reverse=0):
    def testList_nonlinks(self):
        s = _('[List: not a Multilink]')
        self.assertEqual(self.tf.do_list('string'), s)
        self.assertEqual(self.tf.do_list('date'), s)
        self.assertEqual(self.tf.do_list('interval'), s)
        self.assertEqual(self.tf.do_list('password'), s)
        self.assertEqual(self.tf.do_list('link'), s)

    def testList_multilink(self):
        # TODO: test this (needs to have lots and lots of support!
        #self.assertEqual(self.tf.do_list('multilink'),'')
        pass

def suite():
   return unittest.makeSuite(NodeCase, 'test')


#
# $Log: not supported by cvs2svn $
# Revision 1.7  2002/01/23 20:09:41  jhermann
# Proper fix for failing test
#
# Revision 1.6  2002/01/23 05:47:57  richard
# more HTML template cleanup and unit tests
#
# Revision 1.5  2002/01/23 05:10:28  richard
# More HTML template cleanup and unit tests.
#  - download() now implemented correctly, replacing link(is_download=1) [fixed in the
#    templates, but link(is_download=1) will still work for existing templates]
#
# Revision 1.4  2002/01/22 22:46:22  richard
# more htmltemplate cleanups and unit tests
#
# Revision 1.3  2002/01/22 06:35:40  richard
# more htmltemplate tests and cleanup
#
# Revision 1.2  2002/01/22 00:12:07  richard
# Wrote more unit tests for htmltemplate, and while I was at it, I polished
# off the implementation of some of the functions so they behave sanely.
#
# Revision 1.1  2002/01/21 11:05:48  richard
# New tests for htmltemplate (well, it's a beginning)
#
#
#
# vim: set filetype=python ts=4 sw=4 et si
