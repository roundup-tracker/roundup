""" This implements the PostgreSQL full-text indexer.
The table consists of (Class, propname, itemid) instances as columns
along with an _tsv tsvector column. The _tsv column is searched using
@@ and the instances returned.
"""

import re

from roundup.backends.indexer_common import Indexer as IndexerBase
from roundup.i18n import _
from roundup.cgi.exceptions import IndexerQueryError

from psycopg2.errors import InFailedSqlTransaction, SyntaxError, \
                            UndefinedObject


class Indexer(IndexerBase):
    def __init__(self, db):
        IndexerBase.__init__(self, db)
        self.db = db
        if db.conn.server_version < 110000:
            db.sql("select version()")
            server_descr = db.cursor.fetchone()
            raise ValueError("Postgres native_fts indexing requires postgres "
                             "11.0 or newer. Server is version: %s" %
                             server_descr)
        self.reindex = 0
        self.query_language = True

    def close(self):
        """close the indexing database"""
        # just nuke the circular reference
        self.db = None

    def save_index(self):
        """Save the changes to the index."""
        # not necessary - the RDBMS connection will handle this for us
        pass

    def force_reindex(self):
        """Force a reindexing of the database.  This essentially
        empties the __fts table and sets a flag so
        that the databases are reindexed"""
        self.reindex = 1

    def should_reindex(self):
        """returns True if the indexes need to be rebuilt"""
        return self.reindex

    def add_text(self, identifier, text, mime_type='text/plain'):
        """ "identifier" is  (classname, itemid, property) """
        if mime_type != 'text/plain':
            return

        # Ensure all elements of the identifier are strings 'cos the itemid
        # column is varchar even if item ids may be numbers elsewhere in the
        # code. ugh.
        identifier = tuple(map(str, identifier))

        # removed pre-processing of text that incudes only words with:
        # self.minlength <= len(word) <= self.maxlength
        # Not sure if that is correct.

        # first, find the rowid of the (classname, itemid, property)
        a = self.db.arg  # arg is the token for positional parameters
        sql = 'select ctid from __fts where _class=%s and '\
            '_itemid=%s and _prop=%s' % (a, a, a)
        self.db.cursor.execute(sql, identifier)
        r = self.db.cursor.fetchone()
        if not r:
            # not previously indexed
            sql = 'insert into __fts (_class, _itemid, _prop, _tsv)'\
                ' values (%s, %s, %s, to_tsvector(%s, %s))' % (a, a, a, a, a)
            self.db.cursor.execute(sql, identifier +
                                   (self.db.config['INDEXER_LANGUAGE'], text))
        else:
            id = r[0]
            sql = 'update __fts set _tsv=to_tsvector(%s, %s) where ctid=%s' % \
                  (a, a, a)
            self.db.cursor.execute(sql, (self.db.config['INDEXER_LANGUAGE'],
                                         text, id))

    def find(self, wordlist):
        """look up all the words in the wordlist.
           For testing wordlist is actually a list.
           In production, wordlist is a list of a single string
           that is a postgresql websearch_to_tsquery() query.

           https://www.postgresql.org/docs/14/textsearch-controls.html#TEXTSEARCH-PARSING-QUERIES
        """

        if not wordlist:
            return []

        a = self.db.arg  # arg is the token for positional parameters

        # removed filtering of word in wordlist to include only
        # words with:  self.minlength <= len(word) <= self.maxlength
        if wordlist[0].startswith("ts:"):
            wordlist[0] = wordlist[0][3:]
            sql = ('select _class, _itemid, _prop from __fts '
                   'where _tsv @@ to_tsquery(%s, %s)' % (a, a))

        else:
            if re.search(r'[<>!&|()*]', " ".join(wordlist)):
                # assume this is a ts query processed by websearch_to_tsquery.
                # since it has operator characters in it.
                raise IndexerQueryError(_('You have non-word/operator '
                'characters "<>!&|()*" in your query. Did you want to '
                'do a tsquery search and forgot to start it with "ts:"?'))
            else:
                sql = 'select _class, _itemid, _prop from __fts '\
                      'where _tsv @@ websearch_to_tsquery(%s, %s)' % (a, a)

        try:
            # tests supply a multi element word list. Join them.
            self.db.cursor.execute(sql, (self.db.config['INDEXER_LANGUAGE'],
                                         " ".join(wordlist),))
        except SyntaxError as e:
            # reset the cursor as it's invalid currently
            # reuse causes an InFailedSqlTransaction
            self.db.rollback()

            raise IndexerQueryError(e.args[0])
        except InFailedSqlTransaction:
            # reset the cursor as it's invalid currently
            self.db.rollback()
            raise
        except UndefinedObject as e:
            # try for a nicer user error
            self.db.rollback()
            lookfor = ('text search configuration "%s" does '
                       'not exist' % self.db.config['INDEXER_LANGUAGE'])
            if lookfor in e.args[0]:
                raise ValueError(_("Check tracker config.ini for a bad "
                                   "indexer_language setting. Error is: %s") %
                                 e)
            else:
                raise

        return self.db.cursor.fetchall()
