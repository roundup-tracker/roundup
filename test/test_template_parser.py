# $Id: test_template_parser.py,v 1.1 2002-08-02 23:45:41 richard Exp $

import unittest
from roundup import template_parser

class TemplateParserTestCase(unittest.TestCase):
   def testParser(self):
        parser = template_parser.RoundupTemplate()
        s = '''
<table border=0 cellspacing=5 cellpadding=0>
 <tr>
  <td bgcolor="ffffea">
   <property name="prop1">
    <require permission="perm1">
     <display call="field('prop1')">
    <else>
     <display call="plain('prop1')">
    </require>
   </property>
  </td>
 </tr>
</table>

<table border=0 cellspacing=5 cellpadding=0>
 <property name="prop2">
  <tr>
   <td class="form-label">Prop2:</td>
   <td class="form-text">
    <require permission="perm2">
     <display call="field('prop2')">
    <else>
     <display call="plain('prop2')">
    </require>
   </td>
  </tr>
 </property>
</table>'''
        parser.feed(s)
        self.assertEqual(template_parser.display(parser.structure),
'\n<table border="0" cellspacing="5" cellpadding="0">\n <tr>\n  <td bgcolor="ffffea">\n   PROPERTY: [(\'name\', \'prop1\')] \n     TEST: [(\'permission\', \'perm1\')]\n OK...  \n       DISPLAY: [(\'call\', "field(\'prop1\')")]  \n     FAIL...  \n       DISPLAY: [(\'call\', "plain(\'prop1\')")]  \n     \n   \n  </td>\n </tr>\n</table>\n\n<table border="0" cellspacing="5" cellpadding="0">\n PROPERTY: [(\'name\', \'prop2\')] \n  <tr>\n   <td class="form-label">Prop2:</td>\n   <td class="form-text">\n     TEST: [(\'permission\', \'perm2\')]\n OK...  \n       DISPLAY: [(\'call\', "field(\'prop2\')")]  \n     FAIL...  \n       DISPLAY: [(\'call\', "plain(\'prop2\')")]  \n     \n   </td>\n  </tr>\n \n</table>')

def suite():
   return unittest.makeSuite(TemplateParserTestCase, 'test')


#
# $Log: not supported by cvs2svn $
# Revision 1.12  2002/07/14 06:05:50  richard
#  . fixed the date module so that Date(". - 2d") works
#
# Revision 1.11  2002/02/21 23:34:52  richard
# Oops, there's 24 hours in a day, and subtraction of intervals now works
# properly.
#
# Revision 1.10  2002/02/21 23:11:45  richard
#  . fixed some problems in date calculations (calendar.py doesn't handle over-
#    and under-flow). Also, hour/minute/second intervals may now be more than
#    99 each.
#
# Revision 1.9  2002/02/21 06:57:39  richard
#  . Added popup help for classes using the classhelp html template function.
#    - add <display call="classhelp('priority', 'id,name,description')">
#      to an item page, and it generates a link to a popup window which displays
#      the id, name and description for the priority class. The description
#      field won't exist in most installations, but it will be added to the
#      default templates.
#
# Revision 1.8  2002/01/16 07:02:57  richard
#  . lots of date/interval related changes:
#    - more relaxed date format for input
#
# Revision 1.7  2001/08/13 23:01:53  richard
# fixed a 2.1-ism
#
# Revision 1.6  2001/08/07 00:24:43  richard
# stupid typo
#
# Revision 1.5  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.4  2001/07/29 23:32:13  richard
# Fixed bug in unit test ;)
#
# Revision 1.3  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.2  2001/07/29 06:42:20  richard
# Added Interval tests.
#
# Revision 1.1  2001/07/27 06:55:07  richard
# moving tests -> test
#
# Revision 1.2  2001/07/25 04:34:31  richard
# Added id and log to tests files...
#
#
# vim: set filetype=python ts=4 sw=4 et si
