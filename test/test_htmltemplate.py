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
# $Id: test_htmltemplate.py,v 1.3 2002-01-22 06:35:40 richard Exp $ 

import unittest, cgi

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
            return 'the key'
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
        self.assertEqual(self.tf.do_plain('link'), 'the key')

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
<option selected value="1">the key</option>
<option value="2">the key</option>
</select>''')

    def testField_multilink(self):
        self.assertEqual(self.tf.do_field('multilink'),
            '<input name="multilink" size="30" value="the key,the key">')
        self.assertEqual(self.tf.do_field('multilink', size=10),
            '<input name="multilink" size="10" value="the key,the key">')

#    def do_menu(self, property, size=None, height=None, showid=0):
    def testMenu_nonlinks(self):
        self.assertEqual(self.tf.do_menu('string'), _('[Menu: not a link]'))
        self.assertEqual(self.tf.do_menu('date'), _('[Menu: not a link]'))
        self.assertEqual(self.tf.do_menu('interval'), _('[Menu: not a link]'))
        self.assertEqual(self.tf.do_menu('password'), _('[Menu: not a link]'))

    def testMenu_link(self):
        self.assertEqual(self.tf.do_menu('link'), '''<select name="link">
<option value="-1">- no selection -</option>
<option selected value="1">the key</option>
<option value="2">the key</option>
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
<option selected value="1">other1: the key</option>
<option value="2">other2: the key</option>
</select>''')

    def testMenu_multilink(self):
        self.assertEqual(self.tf.do_menu('multilink', height=10),
            '''<select multiple name="multilink" size="10">
<option selected value="1">the key</option>
<option selected value="2">the key</option>
</select>''')
        self.assertEqual(self.tf.do_menu('multilink', size=6, height=10),
            '''<select multiple name="multilink" size="10">
<option selected value="1">the...</option>
<option selected value="2">the...</option>
</select>''')
        self.assertEqual(self.tf.do_menu('multilink', showid=1),
            '''<select multiple name="multilink" size="2">
<option selected value="1">other1: the key</option>
<option selected value="2">other2: the key</option>
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
            '<a href="other1">the key</a>')

    def testLink_multilink(self):
        self.assertEqual(self.tf.do_link('multilink'),
            '<a href="other1">the key</a>, <a href="other2">the key</a>')

def suite():
   return unittest.makeSuite(NodeCase, 'test')


#
# $Log: not supported by cvs2svn $
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
