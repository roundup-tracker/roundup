''' This implements the full-text indexer over two RDBMS tables. The first
is a mapping of words to occurance IDs. The second maps the IDs to (Class,
propname, itemid) instances.
'''
import re

from indexer_dbm import Indexer

class Indexer(Indexer):
    disallows = {'THE':1, 'THIS':1, 'ZZZ':1, 'THAT':1, 'WITH':1}
    def __init__(self, db):
        self.db = db
        self.reindex = 0

    def close(self):
        '''close the indexing database'''
        # just nuke the circular reference
        self.db = None
  
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

        # first, find the id of the (classname, itemid, property)
        a = self.db.arg
        sql = 'select _textid from _textids where _class=%s and '\
            '_itemid=%s and _prop=%s'%(a, a, a)
        self.db.cursor.execute(sql, identifier)
        r = self.db.cursor.fetchone()
        if not r:
            id = self.db.newid('_textids')
            sql = 'insert into _textids (_textid, _class, _itemid, _prop)'\
                ' values (%s, %s, %s, %s)'%(a, a, a, a)
            self.db.cursor.execute(sql, (id, ) + identifier)
        else:
            id = int(r[0])
            # clear out any existing indexed values
            sql = 'delete from _words where _textid=%s'%a
            self.db.cursor.execute(sql, (id, ))

        # ok, find all the words in the text
        wordlist = re.findall(r'\b\w{2,25}\b', str(text).upper())
        words = {}
        for word in wordlist:
            if not self.disallows.has_key(word):
                words[word] = 1
        words = words.keys()

        # for each word, add an entry in the db
        for word in words:
            # don't dupe
            sql = 'select * from _words where _word=%s and _textid=%s'%(a, a)
            self.db.cursor.execute(sql, (word, id))
            if self.db.cursor.fetchall():
                continue
            sql = 'insert into _words (_word, _textid) values (%s, %s)'%(a, a)
            self.db.cursor.execute(sql, (word, id))

    def find(self, wordlist):
        '''look up all the words in the wordlist.
        If none are found return an empty dictionary
        * more rules here
        '''        
        l = [word.upper() for word in wordlist if 26 > len(word) > 2]

        a = ','.join([self.db.arg] * len(l))
        sql = 'select distinct(_textid) from _words where _word in (%s)'%a
        self.db.cursor.execute(sql, tuple(l))
        r = self.db.cursor.fetchall()
        if not r:
            return {}
        a = ','.join([self.db.arg] * len(r))
        sql = 'select _class, _itemid, _prop from _textids '\
            'where _textid in (%s)'%a
        self.db.cursor.execute(sql, tuple([int(id) for (id,) in r]))
        # self.search_index has the results as {some id: identifier} ...
        # sigh
        r = {}
        k = 0
        for c,n,p in self.db.cursor.fetchall():
            key = (str(c), str(n), str(p))
            r[k] = key
            k += 1
        return r

    def save_index(self):
        # the normal RDBMS backend transaction mechanisms will handle this
        pass

    def rollback(self):
        # the normal RDBMS backend transaction mechanisms will handle this
        pass

