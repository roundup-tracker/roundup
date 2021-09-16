# misc tests

import unittest
import roundup.anypy.cmp_
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
