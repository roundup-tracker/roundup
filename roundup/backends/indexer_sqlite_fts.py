""" This implements the full-text indexer using fts5 in sqlite.
The table consists of (Class, propname, itemid) instances as columns
along with a textblob column. The textblob column is searched using
MATCH and the instances returned.

sqlite test commands to manage schema version change required by
this update.

-- check length before and after
select length(schema) from schema;

-- reset from version 7 (with fts index) to version 6
 update schema set schema = (select replace(schema,
   '''version'': 7','''version'': 6') as new_schema from schema);

-- check version. Good thing it's at the front of the schema
 select substr(schema,0,15) from schema;
 {'version': 6,
"""

from roundup.backends.indexer_common import Indexer as IndexerBase
from roundup.i18n import _
from roundup.cgi.exceptions import IndexerQueryError

try:
    import sqlite3 as sqlite
    if sqlite.sqlite_version_info < (3, 9, 0):
        raise ValueError('sqlite minimum version for FTS5 is 3.9.0+ '
                         '- %s found' % sqlite.sqlite_version)
except ImportError:
    raise ValueError('Unable to import sqlite3 to support FTS.')


class Indexer(IndexerBase):
    def __init__(self, db):
        IndexerBase.__init__(self, db)
        self.db = db
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
        sql = 'select rowid from __fts where _class=%s and '\
            '_itemid=%s and _prop=%s' % (a, a, a)
        self.db.cursor.execute(sql, identifier)
        r = self.db.cursor.fetchone()
        if not r:
            # not previously indexed
            sql = 'insert into __fts (_class, _itemid, _prop, _textblob)'\
                ' values (%s, %s, %s, %s)' % (a, a, a, a)
            self.db.cursor.execute(sql, identifier + (text,))
        else:
            id = int(r[0])
            sql = 'update __fts set _textblob=%s where rowid=%s' % \
                  (a, a)
            self.db.cursor.execute(sql, (text, id))

    def find(self, wordlist):
        """look up all the words in the wordlist.
           For testing wordlist is actually a list.
           In production, wordlist is a list of a single string
           that is a sqlite MATCH query.

           https://www.sqlite.org/fts5.html#full_text_query_syntax
        """
        if not wordlist:
            return []

        a = self.db.arg  # arg is the token for positional parameters

        # removed filtering of word in wordlist to include only
        # words with:  self.minlength <= len(word) <= self.maxlength

        sql = 'select _class, _itemid, _prop from __fts '\
              'where _textblob MATCH %s' % a

        try:
            # tests supply a multi element word list. Join them.
            self.db.cursor.execute(sql, (" ".join(wordlist),))
        except sqlite.OperationalError as e:
            if 'no such column' in e.args[0]:
                raise IndexerQueryError(
                    _("Search failed. Try quoting any terms that "
                      "include a '-' and retry the search."))
            else:
                raise IndexerQueryError(e.args[0].replace("fts5:",
                                                          "Query error:"))

        return self.db.cursor.fetchall()
