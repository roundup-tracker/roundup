# misc tests

import unittest
import roundup.anypy.cmp_
from roundup.cgi.accept_language import parse

class AcceptLanguageTest(unittest.TestCase):
    def testParse(self):
        self.assertEqual(parse("da, en-gb;q=0.8, en;q=0.7"),
                         ['da', 'en_gb', 'en'])
        self.assertEqual(parse("en;q=0.2, fr;q=1"), ['fr', 'en'])
        self.assertEqual(parse("zn; q = 0.2 ,pt-br;q =1"), ['pt_br', 'zn'])
        self.assertEqual(parse("es-AR"), ['es_AR'])
        self.assertEqual(parse("es-es-cat"), ['es_es_cat'])
        self.assertEqual(parse(""), [])
        self.assertEqual(parse(None),[])
        self.assertEqual(parse("   "), [])
        self.assertEqual(parse("en,"), ['en'])

class CmpTest(unittest.TestCase):
    def testCmp(self):
        roundup.anypy.cmp_._test()
