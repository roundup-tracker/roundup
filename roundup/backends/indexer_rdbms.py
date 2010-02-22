#$Id: indexer_rdbms.py,v 1.18 2008-09-01 00:43:02 richard Exp $
""" This implements the full-text indexer over two RDBMS tables. The first
is a mapping of words to occurance IDs. The second maps the IDs to (Class,
propname, itemid) instances.
"""
import re
# Python 2.3 ... 2.6 compatibility:
from roundup.anypy.sets_ import set

from roundup.backends.indexer_common import Indexer as IndexerBase

class Indexer(IndexerBase):
    def __init__(self, db):
        IndexerBase.__init__(self, db)
        self.db = db
        self.reindex = 0

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
        empties the tables ids and index and sets a flag so
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

        # first, find the id of the (classname, itemid, property)
        a = self.db.arg
        sql = 'select _textid from __textids where _class=%s and '\
            '_itemid=%s and _prop=%s'%(a, a, a)
        self.db.cursor.execute(sql, identifier)
        r = self.db.cursor.fetchone()
        if not r:
            # not previously indexed
            id = self.db.newid('__textids')
            sql = 'insert into __textids (_textid, _class, _itemid, _prop)'\
                ' values (%s, %s, %s, %s)'%(a, a, a, a)
            self.db.cursor.execute(sql, (id, ) + identifier)
        else:
            id = int(r[0])
            # clear out any existing indexed values
            sql = 'delete from __words where _textid=%s'%a
            self.db.cursor.execute(sql, (id, ))

        # ok, find all the unique words in the text
        if not isinstance(text, unicode):
            text = unicode(text, "utf-8", "replace")
        text = text.upper()
        wordlist = [w.encode("utf-8")
                    for w in re.findall(r'(?u)\b\w{%d,%d}\b'
                                        % (self.minlength, self.maxlength), text)]
        words = set()
        for word in wordlist:
            if self.is_stopword(word): continue
            words.add(word)

        # for each word, add an entry in the db
        sql = 'insert into __words (_word, _textid) values (%s, %s)'%(a, a)
        words = [(word, id) for word in words]
        self.db.cursor.executemany(sql, words)

    def find(self, wordlist):
        """look up all the words in the wordlist.
        If none are found return an empty dictionary
        * more rules here
        """
        if not wordlist:
            return []

        l = [word.upper() for word in wordlist
             if self.minlength <= len(word) <= self.maxlength]
        l = [word for word in l if not self.is_stopword(word)]

        if not l:
            return []

        if self.db.implements_intersect:
            # simple AND search
            sql = 'select distinct(_textid) from __words where _word=%s'%self.db.arg
            sql = '\nINTERSECT\n'.join([sql]*len(l))
            self.db.cursor.execute(sql, tuple(l))
            r = self.db.cursor.fetchall()
            if not r:
                return []
            a = ','.join([self.db.arg] * len(r))
            sql = 'select _class, _itemid, _prop from __textids '\
                'where _textid in (%s)'%a
            self.db.cursor.execute(sql, tuple([int(row[0]) for row in r]))

        else:
            # A more complex version for MySQL since it doesn't implement INTERSECT

            # Construct SQL statement to join __words table to itself
            # multiple times.
            sql = """select distinct(__words1._textid)
                        from __words as __words1 %s
                        where __words1._word=%s %s"""

            join_tmpl = ' left join __words as __words%d using (_textid) \n'
            match_tmpl = ' and __words%d._word=%s \n'

            join_list = []
            match_list = []
            for n in xrange(len(l) - 1):
                join_list.append(join_tmpl % (n + 2))
                match_list.append(match_tmpl % (n + 2, self.db.arg))

            sql = sql%(' '.join(join_list), self.db.arg, ' '.join(match_list))
            self.db.cursor.execute(sql, l)

            r = [x[0] for x in self.db.cursor.fetchall()]
            if not r:
                return []

            a = ','.join([self.db.arg] * len(r))
            sql = 'select _class, _itemid, _prop from __textids '\
                'where _textid in (%s)'%a

            self.db.cursor.execute(sql, tuple(map(int, r)))

        return self.db.cursor.fetchall()

