# misc tests

import pytest
import re
import sys
import time
import unittest

import roundup.anypy.cmp_

from roundup.anypy.strings import StringIO  # define StringIO
from roundup.cgi import cgitb
from roundup.cgi.accept_language import parse

from roundup.support import PrioList, Progress, TruthDict


class AcceptLanguageTest(unittest.TestCase):
    def testParse(self):
        self.assertEqual(parse("da, en-gb;q=0.8, en;q=0.7"),
                         ['da', 'en_gb', 'en'])
        self.assertEqual(parse("da, en-gb;q=0.7, en;q=0.8"),
                         ['da', 'en', 'en_gb'])
        self.assertEqual(parse("en;q=0.2, fr;q=1"), ['fr', 'en'])
        self.assertEqual(parse("zn; q = 0.2 ,pt-br;q =1"), ['pt_br', 'zn'])
        self.assertEqual(parse("pt-br;q =1, zn; q = 0.2"), ['pt_br', 'zn'])
        self.assertEqual(parse("pt-br,zn;q= 0.1, en-US;q=0.5"),
                         ['pt_br', 'en_US', 'zn'])
        # verify that items with q=1.0 are in same output order as input
        self.assertEqual(parse("pt-br,en-US; q=0.5, zn;q= 1.0" ),
                         ['pt_br', 'zn', 'en_US'])
        self.assertEqual(parse("zn;q=1.0;q= 1.0,pt-br,en-US; q=0.5" ),
                         ['zn', 'pt_br', 'en_US'])
        self.assertEqual(parse("es-AR"), ['es_AR'])
        self.assertEqual(parse("es-es-cat"), ['es_es_cat'])
        self.assertEqual(parse(""), [])
        self.assertEqual(parse(None),[])
        self.assertEqual(parse("   "), [])
        self.assertEqual(parse("en,"), ['en'])


class CmpTest(unittest.TestCase):
    def testCmp(self):
        roundup.anypy.cmp_._test()


class PrioListTest(unittest.TestCase):
    def testPL(self):
        start_data = [(3, 33), (1, -2), (2, 10)]
        pl = PrioList(key=lambda x: x[1])
        for i in start_data:
            pl.append(i)

        l = [x for x in pl]
        self.assertEqual(l, [(1, -2), (2, 10), (3, 33)])

        pl = PrioList()
        for i in start_data:
            pl.append(i)

        l = [x for x in pl]
        self.assertEqual(l, [(1, -2), (2, 10), (3, 33)])

class ProgressTest(unittest.TestCase):

    @pytest.fixture(autouse=True)
    def inject_fixtures(self, capsys):
        self._capsys = capsys

    def testProgress(self):
        for x in Progress("5 Items@2 sec:", [1,2,3,4,5]):
            time.sleep(2)

        captured = self._capsys.readouterr()

        split_capture = captured.out.split('\r')

        # lines padded to 75 characters test should be long enough to
        # get an ETA printed at 100%, 80% and 60% hopefully this
        # doesn't become a flakey test on different hardware.
        self.assertIn("5 Items@2 sec:  0%".ljust(75),
                      split_capture)
        self.assertIn("5 Items@2 sec: 60% (ETA 00:00:02)".ljust(75),
                      split_capture)
        self.assertIn("5 Items@2 sec: 100% (ETA 00:00:00)".ljust(75),
                      split_capture)
        print(captured.err)


class TruthDictTest(unittest.TestCase):
    def testTD(self):
        td = TruthDict([])
        # empty TruthDict always returns True.
        self.assertTrue(td['a'])
        self.assertTrue(td['z'])
        self.assertTrue(td[''])
        self.assertTrue(td[None])

        td = TruthDict(['a', 'b', 'c'])
        self.assertTrue(td['a'])
        self.assertFalse(td['z'])


class VersionCheck(unittest.TestCase):
    def test_Version_Check(self):

        # test for valid versions
        from roundup.version_check import VERSION_NEEDED
        self.assertEqual((2, 7), VERSION_NEEDED)
        del(sys.modules['roundup.version_check'])


        # fake an invalid version
        real_ver =  sys.version_info
        sys.version_info = (2, 1)

        # exit is called on failure, but that breaks testing so
        # just return and discard the exit code.
        real_exit = sys.exit 
        sys.exit =  lambda code: code

        # error case uses print(), capture and check
        capturedOutput = StringIO()
        sys.stdout = capturedOutput
        from roundup.version_check import VERSION_NEEDED
        sys.stdout = sys.__stdout__
        self.assertIn("Roundup requires Python 2.7", capturedOutput.getvalue())

        # reset to valid values for future tests
        sys.exit = real_exit
        sys.version_info = real_ver


class CgiTbCheck(unittest.TestCase):

    def test_NiceDict(self):
        d = cgitb.niceDict("    ", { "two": "three", "four": "five" })

        expected = (
            "<tr><td><strong>four</strong></td><td>'five'</td></tr>\n"
            "<tr><td><strong>two</strong></td><td>'three'</td></tr>"
            )

        self.assertEqual(expected, d)

    def test_breaker(self):
        b = cgitb.breaker()

        expected = ('<body bgcolor="white"><font color="white" size="-5">'
                    ' > </font> </table></table></table></table></table>')

        self.assertEqual(expected, b)

    def test_pt_html(self):
        """ templating error """
        try:
            f = 5
            d = a + 4
        except Exception:
            p = cgitb.pt_html(context=2)

        expected2 = """<h1>Templating Error</h1>
<p><b>&lt;type 'exceptions.NameError'&gt;</b>: global name 'a' is not defined</p>
<p class="help">Debugging information follows</p>
<ol>

</ol>
<table style="font-size: 80%; color: gray">
 <tr><th class="header" align="left">Full traceback:</th></tr>
 <tr><td><pre>Traceback (most recent call last):
  File "XX/test/test_misc.py", line XX, in test_pt_html
    d = a + 4
NameError: global name 'a' is not defined
</pre></td></tr>
</table>
<p>&nbsp;</p>"""

        expected3 = """<h1>Templating Error</h1>
<p><b>&lt;class 'NameError'&gt;</b>: name 'a' is not defined</p>
<p class="help">Debugging information follows</p>
<ol>

</ol>
<table style="font-size: 80%; color: gray">
 <tr><th class="header" align="left">Full traceback:</th></tr>
 <tr><td><pre>Traceback (most recent call last):
  File "XX/test/test_misc.py", line XX, in test_pt_html
    d = a + 4
NameError: name 'a' is not defined
</pre></td></tr>
</table>
<p>&nbsp;</p>"""

        expected3_11 = """<h1>Templating Error</h1>
<p><b>&lt;class 'NameError'&gt;</b>: name 'a' is not defined</p>
<p class="help">Debugging information follows</p>
<ol>

</ol>
<table style="font-size: 80%; color: gray">
 <tr><th class="header" align="left">Full traceback:</th></tr>
 <tr><td><pre>Traceback (most recent call last):
  File "XX/test/test_misc.py", line XX, in test_pt_html
    d = a + 4
        ^
NameError: name 'a' is not defined
</pre></td></tr>
</table>
<p>&nbsp;</p>"""

        # allow file directory prefix and line number to change
        p = re.sub(r'\\',r'/', p)  # support windows \ => /
        # [A-Z]?:? optional drive spec on windows
        p = re.sub(r'(File ")[A-Z]?:?/.*/(test/test_misc.py",)', r'\1XX/\2', p)
        p = re.sub(r'(", line )\d*,', r'\1XX,', p)

        print(p)

        if sys.version_info > (3, 11, 0):
            self.assertEqual(expected3_11, p)
        elif sys.version_info > (3, 0, 0):
            self.assertEqual(expected3, p)
        else:
            self.assertEqual(expected2, p)

    def test_html(self):
        """ templating error """
        # enabiling this will cause the test to fail as the variable
        # is included in the live output but not in expected.
        # self.maxDiff = None

        try:
            f = 5
            d = a + 4
        except Exception:
            h = cgitb.html(context=2)

            expected2 = """
<table width="100%" cellspacing=0 cellpadding=2 border=0 summary="heading">
<tr bgcolor="#777777">
<td valign=bottom>&nbsp;<br>
<font color="#ffffff" face="helvetica, arial">&nbsp;<br><font size=+1><strong>NameError</strong>: global name 'a' is not defined</font></font></td
><td align=right valign=bottom
><font color="#ffffff" face="helvetica, arial">Python XX</font></td></tr></table>
    <p>A problem occurred while running a Python script. Here is the sequence of function calls leading up to the error, with the most recent (innermost) call first. The exception attributes are:<br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__class__&nbsp;= &lt;type 'exceptions.NameError'&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__delattr__&nbsp;= &lt;method-wrapper '__delattr__' of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__dict__&nbsp;= {} <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__doc__&nbsp;= 'Name not found globally.' <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__format__&nbsp;= &lt;built-in method __format__ of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__getattribute__&nbsp;= &lt;method-wrapper '__getattribute__' of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__getitem__&nbsp;= &lt;method-wrapper '__getitem__' of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__getslice__&nbsp;= &lt;method-wrapper '__getslice__' of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__hash__&nbsp;= &lt;method-wrapper '__hash__' of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__init__&nbsp;= &lt;method-wrapper '__init__' of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__new__&nbsp;= &lt;built-in method __new__ of type object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__reduce__&nbsp;= &lt;built-in method __reduce__ of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__reduce_ex__&nbsp;= &lt;built-in method __reduce_ex__ of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__repr__&nbsp;= &lt;method-wrapper '__repr__' of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__setattr__&nbsp;= &lt;method-wrapper '__setattr__' of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__setstate__&nbsp;= &lt;built-in method __setstate__ of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__sizeof__&nbsp;= &lt;built-in method __sizeof__ of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__str__&nbsp;= &lt;method-wrapper '__str__' of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__subclasshook__&nbsp;= &lt;built-in method __subclasshook__ of type object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>__unicode__&nbsp;= &lt;built-in method __unicode__ of exceptions.NameError object&gt; <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>args&nbsp;= ("global name 'a' is not defined",) <br><tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt>message&nbsp;= "global name 'a' is not defined"<p>
<table width="100%" bgcolor="#dddddd" cellspacing=0 cellpadding=2 border=0>
<tr><td><a href="file:XX/test/test_misc.py">XX/test/test_misc.py</a> in <strong>test_html</strong>(self=&lt;test.test_misc.CgiTbCheck testMethod=test_html&gt;)</td></tr></table>
<tt><small><font color="#909090">&nbsp;&nbsp;XX</font></small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;f&nbsp;=&nbsp;5<br>
</tt>


<table width="100%" bgcolor="white" cellspacing=0 cellpadding=0 border=0>
<tr><td><tt><small><font color="#909090">&nbsp;&nbsp;XX</font></small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;d&nbsp;=&nbsp;a&nbsp;+&nbsp;4<br>
</tt></td></tr></table>
<tt><small>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</small>&nbsp;</tt><small><font color="#909090"><strong>d</strong>&nbsp;= <em>undefined</em>, <em>global</em> <strong>a</strong>&nbsp;= <em>undefined</em></font></small><br><p>&nbsp;</p>"""

            expected1_3 ="""NameError"""
            expected2_3 =""": name \'a\' is not defined"""
            expected3_3 ="""built-in method __dir__ of NameError object&gt;"""

        # strip file path prefix from href and text
        # /home/user/develop/roundup/test/test_misc.py in test_html
        h = re.sub(r'(file:)/.*/(test/test_misc.py")', r'\1XX/\2', h)
        h = re.sub(r'(/test_misc.py">)/.*/(test/test_misc.py</a>)',
                   r'\1XX/\2', h)
        # replace code line numbers with XX
        h = re.sub(r'(&nbsp;)\d*(</font>)', r'\1XX\2', h)
        # normalize out python version/path
        h = re.sub(r'(Python )[\d.]*<br>[^<]*/python[23]?', r'\1XX', h)

        print(h)

        if sys.version_info > (3, 0, 0):
            self.assertIn(expected1_3, h)
            self.assertIn(expected2_3, h)
            self.assertIn(expected3_3, h)
        else:
            self.assertEqual(expected2, h)
