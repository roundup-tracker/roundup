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

import os, sys, unittest, shutil

import pytest
from roundup.backends import get_backend, have_backend
from roundup.backends.indexer_rdbms import Indexer
from roundup.backends.indexer_common import get_indexer

from roundup.cgi.exceptions import IndexerQueryError

# borrow from other tests
from .db_test_base import setupSchema, config
from .test_postgresql import postgresqlOpener, skip_postgresql
from .test_mysql import mysqlOpener, skip_mysql
from .test_sqlite import sqliteOpener
from .test_anydbm import anydbmOpener

try:
    from unittest import mock
except ImportError:
    import mock

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
    config[('main', 'indexer_language')] = "english"

class IndexerTest(anydbmOpener, unittest.TestCase):

    indexer_name = "native"

    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        self.db = self.module.Database(config, 'admin')

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
        self.assertSeqEqual(self.dex.find([]), [])

    def test_save_load(self):

        # only run for anydbm test
        if ( not type(self) is IndexerTest ):
            pytest.skip("test_save_load tested only for anydbm backend")

        self.dex.add_text(('test', '1', 'foo'), 'b the hello world')
        self.assertSeqEqual(self.dex.find(['hello']), [('test', '1', 'foo')])
        self.dex.save_index()

        # reopen saved db.
        from roundup.backends.indexer_dbm import Indexer
        self.dex = Indexer(db)

        # verify index is unloaded
        self.assertEqual(self.dex.index_loaded(), False)

        # add also calls load_index(), so it should load the first item.
        self.dex.add_text(('test', '2', 'foo'), 'b the olleh world')

        # note find also does a load_index() if not loaded.
        self.assertSeqEqual(self.dex.find(['hello']), [('test', '1', 'foo')])
        self.assertSeqEqual(self.dex.find(['olleh']), [('test', '2', 'foo')])

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

    def test_get_indexer_specified(self):
        """Specify an indexer back end and make sure it's returned"""
        def class_name_of(object):
            """ take and object and return just the class name.
                So in:

                return the class name before "at".

            """
            return(str(object).split()[0])

        old_indexer = self.db.config['INDEXER']
        self.db.config['INDEXER'] = self.indexer_name

        self.assertEqual(class_name_of(self.dex),
              class_name_of(get_indexer(self.db.config, self.db)))

        self.db.config['INDEXER'] = old_indexer

    def test_stopwords(self):
        """Test that we can find a text with a stopword in it."""
        stopword = "with"
        self.assertTrue(self.dex.is_stopword(stopword.upper()))
        self.dex.add_text(('test', '1', 'bar'), '%s hello world' % stopword)
        self.dex.add_text(('test', '2', 'bar'), 'blah a %s world' % stopword)
        self.dex.add_text(('test', '3', 'bar'), 'blah Blub river')
        self.dex.add_text(('test', '4', 'bar'), 'blah river %s' % stopword)
        self.assertSeqEqual(self.dex.find(['with','world']),
                                                    [('test', '1', 'bar'),
                                                     ('test', '2', 'bar')])
    def test_extremewords(self):
        """Testing too short or too long words."""

        # skip this for FTS test
        if ( isinstance(self,sqliteFtsIndexerTest) or
             isinstance(self,postgresqlFtsIndexerTest)):
            pytest.skip("extremewords not tested for native FTS backends")

        short = "b"
        long = "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
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

    def test_casesensitivity(self):
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

    def test_unicode(self):
        """Test with unicode words. see:
           https://issues.roundup-tracker.org/issue1344046"""
        russian=u'\u0440\u0443\u0441\u0441\u043a\u0438\u0439 \u0442\u0435\u043a\u0441\u0442Spr\xfcnge'
        german=u'Spr\xfcnge'
        self.dex.add_text(('test', '1', 'a'), german )
        self.dex.add_text(('test', '2', 'a'), russian + u' ' + german )

        self.assertSeqEqual(self.dex.find([ u'Spr\xfcnge']),
                    [('test', '1', 'a'), ('test', '2', 'a')])
        self.assertSeqEqual(self.dex.find([u'\u0440\u0443\u0441\u0441\u043a\u0438\u0439']),
                            [('test', '2', 'a')])

    def testNullChar(self):
       """Test with null char in string. Postgres FTS will not index
          it will just ignore string for now.
       """
       string="\x00\x01fred\x255"
       self.dex.add_text(('test', '1', 'a'), string)
       self.assertSeqEqual(self.dex.find(string), [])
        
    def tearDown(self):
        shutil.rmtree('test-index')
        if hasattr(self, 'db'):
            self.db.close()
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)

@skip_whoosh
class WhooshIndexerTest(IndexerTest):

    indexer_name = "whoosh"

    def setUp(self):
        IndexerTest.setUp(self)

        if os.path.exists('test-index'):
            shutil.rmtree('test-index')
        os.mkdir('test-index')
        from roundup.backends.indexer_whoosh import Indexer
        self.dex = Indexer(db)
    def tearDown(self):
        IndexerTest.tearDown(self)

@skip_xapian
class XapianIndexerTest(IndexerTest):

    indexer_name = "xapian"

    def setUp(self):
        IndexerTest.setUp(self)

        if os.path.exists('test-index'):
            shutil.rmtree('test-index')
        os.mkdir('test-index')
        from roundup.backends.indexer_xapian import Indexer
        self.dex = Indexer(db)
    def tearDown(self):
        IndexerTest.tearDown(self)

class Get_IndexerTest(anydbmOpener, unittest.TestCase):
    
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        self.db = self.module.Database(config, 'admin')
        # this is the default, but set it in case default
        # changes in future
        self.db.config['INDEXER'] = ''

    def tearDown(self):
        if hasattr(self, 'db'):
            self.db.close()
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)

    @skip_xapian
    def test_xapian_autoselect(self):
        indexer = get_indexer(self.db.config, self.db)
        self.assertIn('roundup.backends.indexer_xapian.Indexer', str(indexer))

    @skip_whoosh
    def test_whoosh_autoselect(self):
        with mock.patch.dict('sys.modules',
                             {'roundup.backends.indexer_xapian': None}):
            indexer = get_indexer(self.db.config, self.db)
        self.assertIn('roundup.backends.indexer_whoosh.Indexer', str(indexer))

    def test_native_autoselect(self):
        with mock.patch.dict('sys.modules',
                             {'roundup.backends.indexer_xapian': None,
                              'roundup.backends.indexer_whoosh': None}):
            indexer = get_indexer(self.db.config, self.db)
        self.assertIn('roundup.backends.indexer_dbm.Indexer', str(indexer))

    def test_invalid_indexer(self):
        """There is code at the end of indexer_common::get_indexer() to
           raise an AssertionError if the indexer name is invalid.
           This should never be triggered. If it is, it means that
           the code in configure.py that validates indexer names
           allows a name through that get_indexer can't handle.

           Simulate that failure and make sure that the
           AssertionError is raised.

        """

        with self.assertRaises(ValueError) as cm:
            self.db.config['INDEXER'] = 'no_such_indexer'

        # mangle things so we can test AssertionError at end
        # get_indexer()
        from roundup.configuration import IndexerOption
        io_orig = IndexerOption.allowed
        io = list(io_orig)
        io.append("unrecognized_indexer")
        IndexerOption.allowed = tuple(io)
        self.db.config['INDEXER'] = "unrecognized_indexer"

        with self.assertRaises(AssertionError) as cm:
            indexer = get_indexer(self.db.config, self.db)

        # unmangle state
        IndexerOption.allowed = io_orig
        self.assertNotIn("unrecognized_indexer", IndexerOption.allowed)
        self.db.config['INDEXER'] = ""

    def test_unsupported_by_db(self):
        """This requires that the db associated with the test
           is not sqlite or postgres. anydbm works fine to trigger
           the error.
        """
        self.db.config['INDEXER'] = 'native-fts'
        with self.assertRaises(AssertionError) as cm:
            get_indexer(self.db.config, self.db)

        self.assertIn("native-fts", cm.exception.args[0])
        self.db.config['INDEXER'] = ''

class RDBMSIndexerTest(object):
    def setUp(self):
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        self.db = self.module.Database(config, 'admin')
        self.dex = Indexer(self.db)
    def tearDown(self):
        if hasattr(self, 'db'):
            # commit any outstanding cursors.
            # close() doesn't actually close file handle on
            #    windows unless commit() is called.
            self.db.commit()
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


@skip_postgresql
class postgresqlFtsIndexerTest(postgresqlOpener, RDBMSIndexerTest, IndexerTest):

    indexer_name = "native-fts"

    def setUp(self):
        postgresqlOpener.setUp(self)
        RDBMSIndexerTest.setUp(self)
        from roundup.backends.indexer_postgresql_fts import Indexer
        self.dex = Indexer(self.db)
        self.dex.db = self.db

    def tearDown(self):
        RDBMSIndexerTest.tearDown(self)
        postgresqlOpener.tearDown(self)

    def test_websearch_syntax(self):
        """Test searches using websearch_to_tsquery. These never throw
           errors regardless of how wacky the input.
        """

        self.dex.add_text(('test', '1', 'foo'), 'a the hello world')
        self.dex.add_text(('test', '2', 'foo'), 'helh blah blah the world')
        self.dex.add_text(('test', '3', 'foo'), 'blah hello the world')
        self.dex.add_text(('test', '4', 'foo'), 'hello blah blech the world')
        self.dex.add_text(('test', '5', 'foo'), 'a car drove')
        self.dex.add_text(('test', '6', 'foo'), 'a car driving itself')
        self.dex.add_text(('test', '7', 'foo'), "let's drive in the car")
        self.dex.add_text(('test', '8', 'foo'), 'a drive-in movie')

        # test two separate words for sanity
        self.assertSeqEqual(self.dex.find(['"hello" "world"']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '3', 'foo'),
                                                     ('test', '4', 'foo')
                                                    ])
        # now check the phrase
        self.assertSeqEqual(self.dex.find(['"hello world"']),
                                                    [('test', '1', 'foo'),
                                                     ])

        # test negation
        self.assertSeqEqual(self.dex.find(['hello world -blech']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '3', 'foo'),
                                                    ])

        # phrase negation
        self.assertSeqEqual(self.dex.find(['hello world -"blah hello"']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '4', 'foo'),
                                                    ])

        # test without or
        self.assertSeqEqual(self.dex.find(['blah blech']),
                                                    [('test', '4', 'foo'),
                                                    ])

        # test with or
        self.assertSeqEqual(self.dex.find(['blah or blech']),
                                                    [ ('test', '2', 'foo'),
                                                      ('test', '3', 'foo'),
                                                      ('test', '4', 'foo'),
                                                    ])

        # stemmer test for english
        self.assertSeqEqual(self.dex.find(['ts:drive']),
                                                    [('test', '6', 'foo'),
                                                     ('test', '7', 'foo'),
                                                     ('test', '8', 'foo')
                                                    ])

        # stemmer is not disabled by quotes 8-(
        self.assertSeqEqual(self.dex.find(['ts:"drive"']),
                                                    [('test', '6', 'foo'),
                                                     ('test', '7', 'foo'),
                                                     ('test', '8', 'foo')
                                                    ])


        # this is missing ts: at the start, so uses the websearch
        # parser. We search for operator characters and wanr the user
        # Otherwise "hello <-> world" is the same as "hello world"
        # and is not a phrase search.
        with self.assertRaises(IndexerQueryError) as ctx:
            self.dex.find(['hello <-> world'])

        self.assertIn('do a tsquery search', ctx.exception.args[0])

    def test_tsquery_syntax(self):
        """Because websearch_to_tsquery doesn't allow prefix searches,
           near searches with any value except 1 (phrase search), allow
           use of to_tsquery by prefixing the search term wih ts:.

           However, unlike websearch_to_tsquery, this will throw a
           psycopg2.errors.SyntaxError on bad input. SyntaxError is
           re-raised as IndexerQueryError.  But it makes a bunch of
           useful expert functionality available.

        """

        self.dex.add_text(('test', '1', 'foo'), 'a the hello world')
        self.dex.add_text(('test', '2', 'foo'), 'helh blah blah the world')
        self.dex.add_text(('test', '3', 'foo'), 'blah hello the world')
        self.dex.add_text(('test', '4', 'foo'), 'hello blah blech the world')
        self.dex.add_text(('test', '5', 'foo'), 'a car drove')
        self.dex.add_text(('test', '6', 'foo'), 'a car driving itself')
        self.dex.add_text(('test', '7', 'foo'), "let's drive in the car")
        self.dex.add_text(('test', '8', 'foo'), 'a drive-in movie')
        self.dex.db.commit()

        # test two separate words for sanity
        self.assertSeqEqual(self.dex.find(['ts:hello & world']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '3', 'foo'),
                                                     ('test', '4', 'foo')
                                                    ])
        # now check the phrase
        self.assertSeqEqual(self.dex.find(['ts:hello <-> world']),
                                                    [('test', '1', 'foo'),
                                                     ])

        # test negation
        self.assertSeqEqual(self.dex.find(['ts:hello & world & !blech']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '3', 'foo'),
                                                    ])

        self.assertSeqEqual(self.dex.find(
            ['ts:hello & world & !(blah <-> hello)']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '4', 'foo'),
                                                    ])

        # test without or
        self.assertSeqEqual(self.dex.find(['ts:blah & blech']),
                                                    [('test', '4', 'foo'),
                                                    ])

        # test with or
        self.assertSeqEqual(self.dex.find(['ts:blah | blech']),
                                                    [ ('test', '2', 'foo'),
                                                      ('test', '3', 'foo'),
                                                      ('test', '4', 'foo'),
                                                    ])
        # stemmer test for english
        self.assertSeqEqual(self.dex.find(['ts:drive']),
                                                    [('test', '6', 'foo'),
                                                     ('test', '7', 'foo'),
                                                     ('test', '8', 'foo')
                                                    ])

        # stemmer is not disabled by quotes 8-(
        self.assertSeqEqual(self.dex.find(['ts:"drive"']),
                                                    [('test', '6', 'foo'),
                                                     ('test', '7', 'foo'),
                                                     ('test', '8', 'foo')
                                                    ])


        # test with syntax error
        with self.assertRaises(IndexerQueryError) as ctx:
            self.dex.find(['ts:blah blech'])

        self.assertEqual(ctx.exception.args[0],
                         'syntax error in tsquery: "blah blech"\n')

        # now check the phrase Note unlike sqlite, order matters,
        # hello must come first.
        self.assertSeqEqual(self.dex.find(['ts:hello <-> world']),
                                                    [('test', '1', 'foo'),
                                                     ])

        # now check the phrase with explicitly 1 intervening item
        self.assertSeqEqual(self.dex.find(['ts:hello <2> world']),
                                                    [('test', '3', 'foo'),
                                                     ])
        # now check the phrase with near explicitly 1 or 3 intervening items
        self.assertSeqEqual(self.dex.find([
            'ts:(hello <4> world) | (hello<2>world)']),
                                                    [('test', '3', 'foo'),
                                                     ('test', '4', 'foo'),
                                                     ])

        # now check the phrase with near explicitly 3 intervening item
        # with prefix for world.
        self.assertSeqEqual(self.dex.find(['ts:hello <4> wor:*']),
                                                    [('test', '4', 'foo'),
                                                     ])

    def test_invalid_language(self):
        import psycopg2

        from roundup.configuration import IndexerOption
        io_orig = IndexerOption.valid_langs

        io = list(io_orig)
        io.append("foo")
        self.db.config["INDEXER_LANGUAGE"] = "foo"

        with self.assertRaises(psycopg2.errors.UndefinedObject) as ctx:
            # psycopg2.errors.UndefinedObject: text search configuration
            #  "foo" does not exist
            self.dex.add_text(('test', '1', 'foo'), 'a the hello world')
        self.assertIn('search configuration "foo" does', ctx.exception.args[0])
        self.db.rollback()

        with self.assertRaises(ValueError) as ctx:
            self.dex.find(['"hello" "world"'])
        self.assertIn('search configuration "foo" does', ctx.exception.args[0])
        self.db.rollback()

        self.db.config["INDEXER_LANGUAGE"] = "english"
        IndexerOption.valid_langs = io_orig

    def testNullChar(self):
       """Test with null char in string. Postgres FTS throws a ValueError
          on indexing which we ignore. This could happen when
          indexing a binary file with a bad mime type. On find, it
          throws a ProgrammingError that we remap to
          IndexerQueryError and pass up. If a null gets to that
          level on search somebody entered it (not sure how you
          could actually do that) but we want a crash in that case
          as the person is probably up to "no good" (R) (TM).

       """
       import psycopg2

       string="\x00\x01fred\x255"
       self.dex.add_text(('test', '1', 'a'), string)
       with self.assertRaises(IndexerQueryError) as ctx:
           self.assertSeqEqual(self.dex.find(string), [])

       self.assertIn("null", ctx.exception.args[0])

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

class sqliteFtsIndexerTest(sqliteOpener, RDBMSIndexerTest, IndexerTest):

    indexer_name = "native-fts"

    def setUp(self):
        RDBMSIndexerTest.setUp(self)
        from roundup.backends.indexer_sqlite_fts import Indexer
        self.dex = Indexer(self.db)
        self.dex.db = self.db

    def test_phrase_and_near(self):
        self.dex.add_text(('test', '1', 'foo'), 'a the hello world')
        self.dex.add_text(('test', '2', 'foo'), 'helh blah blah the world')
        self.dex.add_text(('test', '3', 'foo'), 'blah hello the world')
        self.dex.add_text(('test', '4', 'foo'), 'hello blah blech the world')

        # test two separate words for sanity
        self.assertSeqEqual(self.dex.find(['"hello" "world"']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '3', 'foo'),
                                                     ('test', '4', 'foo')
                                                    ])
        # now check the phrase
        self.assertSeqEqual(self.dex.find(['"hello world"']),
                                                    [('test', '1', 'foo'),
                                                     ])

        # now check the phrase with near explicitly 0 intervening items
        self.assertSeqEqual(self.dex.find(['NEAR(hello world, 0)']),
                                                    [('test', '1', 'foo'),
                                                     ])

        # now check the phrase with near explicitly 1 intervening item
        self.assertSeqEqual(self.dex.find(['NEAR(hello world, 1)']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '3', 'foo'),
                                                     ])
        # now check the phrase with near explicitly 3 intervening item
        self.assertSeqEqual(self.dex.find(['NEAR(hello world, 3)']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '3', 'foo'),
                                                     ('test', '4', 'foo'),
                                                     ])

    def test_prefix(self):
        self.dex.add_text(('test', '1', 'foo'), 'a the hello world')
        self.dex.add_text(('test', '2', 'foo'), 'helh blah blah the world')
        self.dex.add_text(('test', '3', 'foo'), 'blah hello the world')
        self.dex.add_text(('test', '4', 'foo'), 'hello blah blech the world')

        self.assertSeqEqual(self.dex.find(['hel*']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '2', 'foo'),
                                                     ('test', '3', 'foo'),
                                                     ('test', '4', 'foo')
                                                    ])


    def test_bool_start(self):
        self.dex.add_text(('test', '1', 'foo'), 'a the hello world')
        self.dex.add_text(('test', '2', 'foo'), 'helh blah blah the world')
        self.dex.add_text(('test', '3', 'foo'), 'blah hello the world')
        self.dex.add_text(('test', '4', 'foo'), 'hello blah blech the world')

        self.assertSeqEqual(self.dex.find(['hel* NOT helh NOT blech']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '3', 'foo'),
                                                    ])

        self.assertSeqEqual(self.dex.find(['hel* NOT helh NOT blech OR the']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '2', 'foo'),
                                                     ('test', '3', 'foo'),
                                                     ('test', '4', 'foo'),
                                                    ])

        self.assertSeqEqual(self.dex.find(['helh OR hello']),
                                                    [('test', '1', 'foo'),
                                                     ('test', '2', 'foo'),
                                                     ('test', '3', 'foo'),
                                                     ('test', '4', 'foo'),
                                                    ])


        self.assertSeqEqual(self.dex.find(['helh AND hello']),
                                                    [])
        # matches if line starts with hello
        self.assertSeqEqual(self.dex.find(['^hello']),
                                                    [
                                                     ('test', '4', 'foo'),
                                                    ])

        self.assertSeqEqual(self.dex.find(['hello']),
                                                    [
                                                     ('test', '1', 'foo'),
                                                     ('test', '3', 'foo'),
                                                     ('test', '4', 'foo'),
                                                    ])

    def test_query_errors(self):
        """test query phrases that generate an error. Also test the
           correction"""

        self.dex.add_text(('test', '1', 'foo'), 'a the hello-world')
        self.dex.add_text(('test', '2', 'foo'), 'helh blah blah the world')
        self.dex.add_text(('test', '3', 'foo'), 'blah hello the world')
        self.dex.add_text(('test', '4', 'foo'), 'hello blah blech the world')

        # handle known error that roundup recognizes and tries to diagnose
        with self.assertRaises(IndexerQueryError) as ctx:
            self.dex.find(['the hello-world'])

        error = ( "Search failed. Try quoting any terms that include a '-' "
                  "and retry the search.")
        self.assertEqual(str(ctx.exception), error)


        self.assertSeqEqual(self.dex.find(['the "hello-world"']),
                                                    [('test', '1', 'foo'),
                                                    ])

        # handle known error that roundup recognizes and tries to diagnose
        with self.assertRaises(IndexerQueryError) as ctx:
                self.dex.find(['hello world + ^the'])

        error = 'Query error: syntax error near "^"'
        self.assertEqual(str(ctx.exception), error)

    def testNullChar(self):
       """Test with null char in string. FTS will throw
          an error on null.
       """
       string="\x00\x01fred\x255"
       self.dex.add_text(('test', '1', 'a'), string)
       with self.assertRaises(IndexerQueryError) as cm:
           self.assertSeqEqual(self.dex.find(string), [])

# vim: set filetype=python ts=4 sw=4 et si
