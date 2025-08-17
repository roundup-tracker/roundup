''' This implements the full-text indexer using the Xapian indexer.
'''
import os
import re
import time
import xapian

from roundup.anypy.strings import b2s, s2b
from roundup.backends.indexer_common import Indexer as IndexerBase
from roundup.i18n import _

# Note that Xapian always uses UTF-8 encoded string, see
# https://xapian.org/docs/bindings/python3/introduction.html#strings:
# "Where std::string is returned, it's always mapped to bytes in
# Python..."


class Indexer(IndexerBase):
    def __init__(self, db):
        IndexerBase.__init__(self, db)
        self.db_path = db.config.DATABASE
        self.reindex = 0
        self.transaction_active = False

    def _get_database(self):
        index = os.path.join(self.db_path, 'text-index')
        for n in range(10):
            try:
                # if successful return
                return xapian.WritableDatabase(index, xapian.DB_CREATE_OR_OPEN)
            except xapian.DatabaseLockError:
                # adaptive sleep. Get longer as count increases.
                time_to_sleep = 0.01 * (2 << min(5, n))
                time.sleep(time_to_sleep)
                # we are back to the for loop

        # Get here only if we dropped out of the for loop.
        raise xapian.DatabaseLockError(_(
            "Unable to get lock after 10 retries on %s.") % index)

    def save_index(self):
        '''Save the changes to the index.'''
        if not self.transaction_active:
            return
        database = self._get_database()
        database.commit_transaction()
        self.transaction_active = False

    def close(self):
        '''close the indexing database'''
        pass

    def rollback(self):
        if not self.transaction_active:
            return
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
        if not text:
            text = ''

        # open the database and start a transaction if needed
        database = self._get_database()

        # XXX: Xapian now supports transactions,
        #  but there is a call to save_index() missing.
        # if not self.transaction_active:
        #      database.begin_transaction()
        #      self.transaction_active = True

        stemmer = xapian.Stem(self.language)

        # We use the identifier twice: once in the actual "text" being
        # indexed so we can search on it, and again as the "data" being
        # indexed so we know what we're matching when we get results
        identifier = s2b('%s:%s:%s' % identifier)

        # create the new document
        doc = xapian.Document()
        doc.set_data(identifier)
        doc.add_term(identifier, 0)

        for match in re.finditer(r'\b\w{%d,%d}\b'
                                 % (self.minlength, self.maxlength),
                                 text.upper(), re.UNICODE):
            word = match.group(0)
            if self.is_stopword(word):
                continue
            term = stemmer(s2b(word.lower()))
            doc.add_posting(term, match.start(0))

        database.replace_document(identifier, doc)

    def find(self, wordlist):
        '''look up all the words in the wordlist.
        If none are found return an empty dictionary
        * more rules here
        '''
        if not wordlist:
            return {}

        database = self._get_database()

        enquire = xapian.Enquire(database)
        stemmer = xapian.Stem(self.language)
        terms = []
        for term in [word.upper() for word in wordlist
                     if self.minlength <= len(word) <= self.maxlength]:
            if not self.is_stopword(term):
                terms.append(stemmer(s2b(term.lower())))
        query = xapian.Query(xapian.Query.OP_AND, terms)

        enquire.set_query(query)
        matches = enquire.get_mset(0, database.get_doccount())

        return [tuple(b2s(m.document.get_data()).split(':'))
                for m in matches]
