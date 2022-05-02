# misc tests

import unittest
import roundup.anypy.cmp_
import sys
from roundup.anypy.strings import StringIO  # define StringIO
from roundup.cgi.accept_language import parse

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


