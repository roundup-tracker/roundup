#$Id: indexer_xapian.py,v 1.4 2006-02-10 00:16:13 richard Exp $
''' This implements the full-text indexer using the Xapian indexer.
'''
import re, os

import xapian

from roundup.backends.indexer_common import Indexer as IndexerBase

# TODO: we need to delete documents when a property is *reindexed*

class Indexer(IndexerBase):
    def __init__(self, db):
        IndexerBase.__init__(self, db)
        self.db_path = db.config.DATABASE
        self.reindex = 0
        self.transaction_active = False

    def _get_database(self):
        index = os.path.join(self.db_path, 'text-index')
        return xapian.WritableDatabase(index, xapian.DB_CREATE_OR_OPEN)

    def save_index(self):
        '''Save the changes to the index.'''
        if not self.transaction_active:
            return
        # XXX: Xapian databases don't actually implement transactions yet
        database = self._get_database()
        database.commit_transaction()
        self.transaction_active = False

    def close(self):
        '''close the indexing database'''
        pass
  
    def rollback(self):
        if not self.transaction_active:
            return
        # XXX: Xapian databases don't actually implement transactions yet
        database = self._get_database()
        database.cancel_transaction()
        self.transaction_active = False

    def force_reindex(self):
        '''Force a reindexing of the database.  This essentially
        empties the tables ids and index and sets a flag so
        that the databases are reindexed'''
        self.reindex = 1

    def should_reindex(self):
        '''returns True if the indexes need to be rebuilt'''
        return self.reindex

    def add_text(self, identifier, text, mime_type='text/plain'):
        ''' "identifier" is  (classname, itemid, property) '''
        if mime_type != 'text/plain':
            return
        if not text: text = ''

        # open the database and start a transaction if needed
        database = self._get_database()
        # XXX: Xapian databases don't actually implement transactions yet
        #if not self.transaction_active:
            #database.begin_transaction()
            #self.transaction_active = True

        # TODO: allow configuration of other languages
        stemmer = xapian.Stem("english")

        # We use the identifier twice: once in the actual "text" being
        # indexed so we can search on it, and again as the "data" being
        # indexed so we know what we're matching when we get results
        identifier = '%s:%s:%s'%identifier

        # see if the id is in the database
        enquire = xapian.Enquire(database)
        query = xapian.Query(xapian.Query.OP_AND, [identifier])
        enquire.set_query(query)
        matches = enquire.get_mset(0, 10)
        if matches.size():      # would it killya to implement __len__()??
            b = matches.begin()
            docid = b.get_docid()
        else:
            docid = None

        # create the new document
        doc = xapian.Document()
        doc.set_data(identifier)
        doc.add_posting(identifier, 0)

        for match in re.finditer(r'\b\w{2,25}\b', text.upper()):
            word = match.group(0)
            if self.is_stopword(word):
                continue
            term = stemmer.stem_word(word)
            doc.add_posting(term, match.start(0))
        if docid:
            database.replace_document(docid, doc)
        else:
            database.add_document(doc)

    def find(self, wordlist):
        '''look up all the words in the wordlist.
        If none are found return an empty dictionary
        * more rules here
        '''        
        if not wordlist:
            return {}

        database = self._get_database()

        enquire = xapian.Enquire(database)
        stemmer = xapian.Stem("english")
        terms = []
        for term in [word.upper() for word in wordlist if 26 > len(word) > 2]:
            terms.append(stemmer.stem_word(term.upper()))
        query = xapian.Query(xapian.Query.OP_AND, terms)

        enquire.set_query(query)
        matches = enquire.get_mset(0, 10)

        return [tuple(m[xapian.MSET_DOCUMENT].get_data().split(':'))
            for m in matches]

