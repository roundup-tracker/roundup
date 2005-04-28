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

# $Id: test_indexer.py,v 1.7 2005-04-28 00:21:42 richard Exp $

import os, unittest, shutil

class IndexerTest(unittest.TestCase):
    def setUp(self):
        if os.path.exists('test-index'):
            shutil.rmtree('test-index')
        os.mkdir('test-index')
        os.mkdir('test-index/files')
        from roundup.backends.indexer_dbm import Indexer
        self.dex = Indexer('test-index')
        self.dex.load_index()

    def test_basics(self):
        self.dex.add_text(('test', '1', 'foo'), 'a the hello world')
        self.dex.add_text(('test', '2', 'foo'), 'blah blah the world')
        self.assertEqual(self.dex.find(['world']), [('test', '1', 'foo'),
                                                    ('test', '2', 'foo')])
        self.assertEqual(self.dex.find(['blah']), [('test', '2', 'foo')])
        self.assertEqual(self.dex.find(['blah', 'hello']), [])

    def tearDown(self):
        shutil.rmtree('test-index')

class XapianIndexerTest(IndexerTest):
    def setUp(self):
        if os.path.exists('text-index'):
            shutil.rmtree('text-index')
        from roundup.backends.indexer_xapian import Indexer
        self.dex = Indexer('.')
    def tearDown(self):
        shutil.rmtree('text-index')

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(IndexerTest))
    try:
        import xapian
        suite.addTest(unittest.makeSuite(XapianIndexerTest))
    except ImportError:
        print "Skipping Xapian indexer tests"
        pass
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: set filetype=python ts=4 sw=4 et si
