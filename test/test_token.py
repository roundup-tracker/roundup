#
# Copyright (c) 2001 Richard Jones
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

import unittest, time

from roundup.token import token_split

class TokenTestCase(unittest.TestCase):
    def testValid(self):
        l = token_split('hello world')
        self.assertEqual(l, ['hello', 'world'])

    def testIgnoreExtraSpace(self):
        l = token_split('hello  world ')
        self.assertEqual(l, ['hello', 'world'])

    def testQuoting(self):
        l = token_split('"hello world"')
        self.assertEqual(l, ['hello world'])
        l = token_split("'hello world'")
        self.assertEqual(l, ['hello world'])

    def testEmbedQuote(self):
        l = token_split(r'Roch\'e Compaan')
        self.assertEqual(l, ["Roch'e", "Compaan"])
        l = token_split('address="1 2 3"')
        self.assertEqual(l, ['address=1 2 3'])

    def testEscaping(self):
        l = token_split('"Roch\'e" Compaan')
        self.assertEqual(l, ["Roch'e", "Compaan"])
        l = token_split(r'hello\ world')
        self.assertEqual(l, ['hello world'])
        l = token_split(r'\\')
        self.assertEqual(l, ['\\'])
        l = token_split(r'\n')
        self.assertEqual(l, ['\n'])

    def testBadQuote(self):
        self.assertRaises(ValueError, token_split, '"hello world')
        self.assertRaises(ValueError, token_split, "Roch'e Compaan")

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TokenTestCase))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: set filetype=python ts=4 sw=4 et si
