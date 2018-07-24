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

import os, unittest, shutil

import pytest
from roundup.backends import get_backend, have_backend
from roundup.backends.indexer_rdbms import Indexer

# borrow from other tests
from .db_test_base import setupSchema, config
from .test_postgresql import postgresqlOpener, skip_postgresql
from .test_mysql import mysqlOpener, skip_mysql
from .test_sqlite import sqliteOpener

try:
    import xapian
    skip_xapian = lambda func, *args, **kwargs: func
except ImportError:
    # FIX: workaround for a bug in pytest.mark.skip():
    #   https://github.com/pytest-dev/pytest/issues/568
    from .pytest_patcher import mark_class
    skip_xapian = mark_class(pytest.mark.skip(
        "Skipping Xapian indexer tests: 'xapian' not installed"))

try:
    import whoosh
    skip_whoosh = lambda func, *args, **kwargs: func
except ImportError:
    # FIX: workaround for a bug in pytest.mark.skip():
    #   https://github.com/pytest-dev/pytest/issues/568
    from .pytest_patcher import mark_class
    skip_whoosh = mark_class(pytest.mark.skip(
        "Skipping Whoosh indexer tests: 'whoosh' not installed"))


class db:
    class config(dict):
        DATABASE = 'test-index'
    config = config()
    config[('main', 'indexer_stopwords')] = []

class IndexerTest(unittest.TestCase):
    def setUp(self):
        if os.path.exists('test-index'):
            shutil.rmtree('test-index')
        os.mkdir('test-index')
        os.mkdir('test-index/files')
        from roundup.backends.indexer_dbm import Indexer
        self.dex = Indexer(db)
        self.dex.load_index()

    def assertSeqEqual(self, s1, s2):
        # First argument is the db result we're testing, second is the
        # desired result. Some db results don't have iterable rows, so we
        # have to work around that.
        # Also work around some dbs not returning items in the expected
        # order.
        s1 = list([tuple([r[n] for n in range(len(r))]) for r in s1])
        s1.sort()
        if s1 != s2:
            self.fail('contents of %r != %r'%(s1, s2))

    def test_basics(self):
        self.dex.add_text(('test', '1', 'foo'), 'a the hello world')
        self.dex.add_text(('test', '2', 'foo'), 'blah blah the world')
        self.assertSeqEqual(self.dex.find(['world']), [('test', '1', 'foo'),
                                                    ('test', '2', 'foo')])
        self.assertSeqEqual(self.dex.find(['blah']), [('test', '2', 'foo')])
        self.assertSeqEqual(self.dex.find(['blah', 'hello']), [])

    def test_change(self):
        self.dex.add_text(('test', '1', 'foo'), 'a the hello world')
        self.dex.add_text(('test', '2', 'foo'), 'blah blah the world')
        self.assertSeqEqual(self.dex.find(['world']), [('test', '1', 'foo'),
                                                    ('test', '2', 'foo')])
        self.dex.add_text(('test', '1', 'foo'), 'a the hello')
        self.assertSeqEqual(self.dex.find(['world']), [('test', '2', 'foo')])

    def test_clear(self):
        self.dex.add_text(('test', '1', 'foo'), 'a the hello world')
        self.dex.add_text(('test', '2', 'foo'), 'blah blah the world')
        self.assertSeqEqual(self.dex.find(['world']), [('test', '1', 'foo'),
                                                    ('test', '2', 'foo')])
        self.dex.add_text(('test', '1', 'foo'), '')
        self.assertSeqEqual(self.dex.find(['world']), [('test', '2', 'foo')])

    def test_stopwords(self):
        """Test that we can find a text with a stopword in it."""
        stopword = "with"
        self.assert_(self.dex.is_stopword(stopword.upper()))
        self.dex.add_text(('test', '1', 'bar'), '%s hello world' % stopword)
        self.dex.add_text(('test', '2', 'bar'), 'blah a %s world' % stopword)
        self.dex.add_text(('test', '3', 'bar'), 'blah Blub river')
        self.dex.add_text(('test', '4', 'bar'), 'blah river %s' % stopword)
        self.assertSeqEqual(self.dex.find(['with','world']),
                                                    [('test', '1', 'bar'),
                                                     ('test', '2', 'bar')])
    def test_extremewords(self):
        """Testing too short or too long words."""
        short = "b"
        long = "abcdefghijklmnopqrstuvwxyz"
        self.dex.add_text(('test', '1', 'a'), '%s hello world' % short)
        self.dex.add_text(('test', '2', 'a'), 'blah a %s world' % short)
        self.dex.add_text(('test', '3', 'a'), 'blah Blub river')
        self.dex.add_text(('test', '4', 'a'), 'blah river %s %s'
                                                        % (short, long))
        self.assertSeqEqual(self.dex.find([short,'world', long, short]),
                                                    [('test', '1', 'a'),
                                                     ('test', '2', 'a')])
        self.assertSeqEqual(self.dex.find([long]),[])

        # special test because some faulty code indexed length(word)>=2
        # but only considered length(word)>=3 to be significant
        self.dex.add_text(('test', '5', 'a'), 'blah py %s %s'
                                                        % (short, long))
        self.assertSeqEqual(self.dex.find(["py"]), [('test', '5', 'a')])

    def test_casesensitity(self):
        """Test if searches are case-in-sensitive."""
        self.dex.add_text(('test', '1', 'a'), 'aaaa bbbb')
        self.dex.add_text(('test', '2', 'a'), 'aAaa BBBB')
        self.assertSeqEqual(self.dex.find(['aaaa']),
                                                    [('test', '1', 'a'),
                                                     ('test', '2', 'a')])
        self.assertSeqEqual(self.dex.find(['BBBB']),
                                                    [('test', '1', 'a'),
                                                     ('test', '2', 'a')])

    def test_wordsplitting(self):
        """Test if word splitting works."""
        self.dex.add_text(('test', '1', 'a'), 'aaaa-aaa bbbb*bbb')
        self.dex.add_text(('test', '2', 'a'), 'aaaA-aaa BBBB*BBB')
        for k in 'aaaa', 'aaa', 'bbbb', 'bbb':
            self.assertSeqEqual(self.dex.find([k]),
                [('test', '1', 'a'), ('test', '2', 'a')])

    def test_manyresults(self):
        """Test if searches find many results."""
        for i in range(123):
            self.dex.add_text(('test', str(i), 'many'), 'many')
        self.assertEqual(len(self.dex.find(['many'])), 123)

    def tearDown(self):
        shutil.rmtree('test-index')

@skip_whoosh
class WhooshIndexerTest(IndexerTest):
    def setUp(self):
        if os.path.exists('test-index'):
            shutil.rmtree('test-index')
        os.mkdir('test-index')
        from roundup.backends.indexer_whoosh import Indexer
        self.dex = Indexer(db)
    def tearDown(self):
        shutil.rmtree('test-index')

@skip_xapian
class XapianIndexerTest(IndexerTest):
    def setUp(self):
        if os.path.exists('test-index'):
            shutil.rmtree('test-index')
        os.mkdir('test-index')
        from roundup.backends.indexer_xapian import Indexer
        self.dex = Indexer(db)
    def tearDown(self):
        shutil.rmtree('test-index')


class RDBMSIndexerTest(object):
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        self.db = self.module.Database(config, 'admin')
        self.dex = Indexer(self.db)
    def tearDown(self):
        if hasattr(self, 'db'):
            self.db.close()
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)


@skip_postgresql
class postgresqlIndexerTest(postgresqlOpener, RDBMSIndexerTest, IndexerTest):
    def setUp(self):
        postgresqlOpener.setUp(self)
        RDBMSIndexerTest.setUp(self)
    def tearDown(self):
        RDBMSIndexerTest.tearDown(self)
        postgresqlOpener.tearDown(self)


@skip_mysql
class mysqlIndexerTest(mysqlOpener, RDBMSIndexerTest, IndexerTest):
    def setUp(self):
        mysqlOpener.setUp(self)
        RDBMSIndexerTest.setUp(self)
    def tearDown(self):
        RDBMSIndexerTest.tearDown(self)
        mysqlOpener.tearDown(self)


class sqliteIndexerTest(sqliteOpener, RDBMSIndexerTest, IndexerTest):
    pass

# vim: set filetype=python ts=4 sw=4 et si
