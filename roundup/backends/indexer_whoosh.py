''' This implements the full-text indexer using Whoosh.
'''
import os

from whoosh import fields, qparser, index, query, analysis

from roundup.backends.indexer_common import Indexer as IndexerBase
from roundup.anypy.strings import us2u


class Indexer(IndexerBase):
    def __init__(self, db):
        IndexerBase.__init__(self, db)
        self.db_path = db.config.DATABASE
        self.reindex = 0
        self.writer = None
        self.index = None
        self.deleted = set()

    def _get_index(self):
        if self.index is None:
            path = os.path.join(self.db_path, 'whoosh-index')
            if not os.path.exists(path):
                # StandardAnalyzer lowercases all words and configure it to
                # block stopwords and words with lengths not between
                # self.minlength and self.maxlength from indexer_common
                stopfilter = analysis.StandardAnalyzer(  #stoplist=self.stopwords,
                                                        minsize=self.minlength,
                                                        maxsize=self.maxlength)
                os.mkdir(path)
                schema = fields.Schema(identifier=fields.ID(stored=True,
                                                            unique=True),
                                   content=fields.TEXT(analyzer=stopfilter))
                index.create_in(path, schema)
            self.index = index.open_dir(path)
        return self.index

    def save_index(self):
        '''Save the changes to the index.'''
        if not self.writer:
            return
        self.writer.commit()
        self.deleted = set()
        self.writer = None

    def close(self):
        '''close the indexing database'''
        pass

    def rollback(self):
        if not self.writer:
            return
        self.writer.cancel()
        self.deleted = set()
        self.writer = None

    def force_reindex(self):
        '''Force a reindexing of the database.  This essentially
        empties the tables ids and index and sets a flag so
        that the databases are reindexed'''
        self.reindex = 1

    def should_reindex(self):
        '''returns True if the indexes need to be rebuilt'''
        return self.reindex

    def _get_writer(self):
        if self.writer is None:
            self.writer = self._get_index().writer()
        return self.writer

    def _get_searcher(self):
        return self._get_index().searcher()

    def add_text(self, identifier, text, mime_type='text/plain'):
        ''' "identifier" is  (classname, itemid, property) '''
        if mime_type != 'text/plain':
            return

        if not text:
            text = u''

        text = us2u(text, "replace")

        # We use the identifier twice: once in the actual "text" being
        # indexed so we can search on it, and again as the "data" being
        # indexed so we know what we're matching when we get results
        identifier = u"%s:%s:%s" % identifier

        # FIXME need to enhance this to handle the whoosh.store.LockError
        # that maybe raised if there is already another process with a lock.
        writer = self._get_writer()

        # Whoosh gets upset if a document is deleted twice in one transaction,
        # so we keep a list of the documents we have so far deleted to make
        # sure that we only delete them once.
        if identifier not in self.deleted:
            searcher = self._get_searcher()
            results = searcher.search(query.Term("identifier", identifier))
            if len(results) > 0:
                writer.delete_by_term("identifier", identifier)
                self.deleted.add(identifier)

        # Note: use '.lower()' because it seems like Whoosh gets
        # better results that way.
        writer.add_document(identifier=identifier, content=text)
        self.save_index()

    def find(self, wordlist):
        '''look up all the words in the wordlist.
        If none are found return an empty dictionary
        * more rules here
        '''

        wordlist = [word for word in wordlist
                    if (self.minlength <= len(word) <= self.maxlength) and
                    not self.is_stopword(word.upper())]

        if not wordlist:
            return {}

        searcher = self._get_searcher()
        q = query.And([query.FuzzyTerm("content", word.lower())
                        for word in wordlist])

        results = searcher.search(q, limit=None)

        return [tuple(result["identifier"].split(':'))
                for result in results]
