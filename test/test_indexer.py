# Copyright (c) 2002 ekit.com Inc (http://www.ekit-inc.com/)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# $Id: test_indexer.py,v 1.5 2004-11-29 02:55:47 richard Exp $

import os, unittest, shutil

from roundup.backends.indexer_dbm import Indexer

class IndexerTest(unittest.TestCase):
    def setUp(self):
        if os.path.exists('test-index'):
            shutil.rmtree('test-index')
        os.mkdir('test-index')
        os.mkdir('test-index/files')
        self.dex = Indexer('test-index')
        self.dex.load_index()

    def test_basics(self):
        self.dex.add_text('testing1', 'a the hello world')
        self.assertEqual(self.dex.words, {'HELLO': {1: 1}, 'WORLD': {1: 1}})
        self.dex.add_text('testing2', 'blah blah the world')
        self.assertEqual(self.dex.words, {'BLAH': {2: 2}, 'HELLO': {1: 1},
            'WORLD': {2: 1, 1: 1}})
        self.assertEqual(self.dex.find(['world']), {2: 'testing2',
            1: 'testing1'})
        self.assertEqual(self.dex.find(['blah']), {2: 'testing2'})
        self.assertEqual(self.dex.find(['blah', 'hello']), {})
        self.dex.save_index()

    def tearDown(self):
        shutil.rmtree('test-index')

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(IndexerTest))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: set filetype=python ts=4 sw=4 et si
