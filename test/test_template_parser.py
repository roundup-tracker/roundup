# $Id: test_template_parser.py,v 1.2 2002-09-10 00:19:55 richard Exp $

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


# vim: set filetype=python ts=4 sw=4 et si
