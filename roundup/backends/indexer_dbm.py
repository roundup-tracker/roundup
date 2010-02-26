#
# This module is derived from the module described at:
#   http://gnosis.cx/publish/programming/charming_python_15.txt
# 
# Author: David Mertz (mertz@gnosis.cx)
# Thanks to: Pat Knight (p.knight@ktgroup.co.uk)
#            Gregory Popovitch (greg@gpy.com)
# 
# The original module was released under this license, and remains under
# it:
#
#     This file is released to the public domain.  I (dqm) would
#     appreciate it if you choose to keep derived works under terms
#     that promote freedom, but obviously am giving up any rights
#     to compel such.
# 
#$Id: indexer_dbm.py,v 1.9 2006-04-27 05:48:26 richard Exp $
'''This module provides an indexer class, RoundupIndexer, that stores text
indices in a roundup instance.  This class makes searching the content of
messages, string properties and text files possible.
'''
__docformat__ = 'restructuredtext'

import os, shutil, re, mimetypes, marshal, zlib, errno
from roundup.hyperdb import Link, Multilink
from roundup.backends.indexer_common import Indexer as IndexerBase

class Indexer(IndexerBase):
    '''Indexes information from roundup's hyperdb to allow efficient
    searching.

    Three structures are created by the indexer::

          files   {identifier: (fileid, wordcount)}
          words   {word: {fileid: count}}
          fileids {fileid: identifier}

    where identifier is (classname, nodeid, propertyname)
    '''
    def __init__(self, db):
        IndexerBase.__init__(self, db)
        self.indexdb_path = os.path.join(db.config.DATABASE, 'indexes')
        self.indexdb = os.path.join(self.indexdb_path, 'index.db')
        self.reindex = 0
        self.quiet = 9
        self.changed = 0

        # see if we need to reindex because of a change in code
        version = os.path.join(self.indexdb_path, 'version')
        if (not os.path.exists(self.indexdb_path) or
                not os.path.exists(version)):
            # for now the file itself is a flag
            self.force_reindex()
        elif os.path.exists(version):
            version = open(version).read()
            # check the value and reindex if it's not the latest
            if version.strip() != '1':
                self.force_reindex()

    def force_reindex(self):
        '''Force a reindex condition
        '''
        if os.path.exists(self.indexdb_path):
            shutil.rmtree(self.indexdb_path)
        os.makedirs(self.indexdb_path)
        os.chmod(self.indexdb_path, 0775)
        open(os.path.join(self.indexdb_path, 'version'), 'w').write('1\n')
        self.reindex = 1
        self.changed = 1

    def should_reindex(self):
        '''Should we reindex?
        '''
        return self.reindex

    def add_text(self, identifier, text, mime_type='text/plain'):
        '''Add some text associated with the (classname, nodeid, property)
        identifier.
        '''
        # make sure the index is loaded
        self.load_index()

        # remove old entries for this identifier
        if identifier in self.files:
            self.purge_entry(identifier)

        # split into words
        words = self.splitter(text, mime_type)

        # Find new file index, and assign it to identifier
        # (_TOP uses trick of negative to avoid conflict with file index)
        self.files['_TOP'] = (self.files['_TOP'][0]-1, None)
        file_index = abs(self.files['_TOP'][0])
        self.files[identifier] = (file_index, len(words))
        self.fileids[file_index] = identifier

        # find the unique words
        filedict = {}
        for word in words:
            if self.is_stopword(word):
                continue
            if word in filedict:
                filedict[word] = filedict[word]+1
            else:
                filedict[word] = 1

        # now add to the totals
        for word in filedict:
            # each word has a dict of {identifier: count}
            if word in self.words:
                entry = self.words[word]
            else:
                # new word
                entry = {}
                self.words[word] = entry

            # make a reference to the file for this word
            entry[file_index] = filedict[word]

        # save needed
        self.changed = 1

    def splitter(self, text, ftype):
        '''Split the contents of a text string into a list of 'words'
        '''
        if ftype == 'text/plain':
            words = self.text_splitter(text)
        else:
            return []
        return words

    def text_splitter(self, text):
        """Split text/plain string into a list of words
        """
        # case insensitive
        text = str(text).upper()

        # Split the raw text
        return re.findall(r'\b\w{%d,%d}\b' % (self.minlength, self.maxlength),
                          text)

    # we override this to ignore too short and too long words
    # and also to fix a bug - the (fail) case.
    def find(self, wordlist):
        '''Locate files that match ALL the words in wordlist
        '''
        if not hasattr(self, 'words'):
            self.load_index()
        self.load_index(wordlist=wordlist)
        entries = {}
        hits = None
        for word in wordlist:
            if not self.minlength <= len(word) <= self.maxlength:
                # word outside the bounds of what we index - ignore
                continue
            word = word.upper()
            if self.is_stopword(word):
                continue
            entry = self.words.get(word)    # For each word, get index
            entries[word] = entry           #   of matching files
            if not entry:                   # Nothing for this one word (fail)
                return {}
            if hits is None:
                hits = {}
                for k in entry:
                    if k not in self.fileids:
                        raise ValueError('Index is corrupted: re-generate it')
                    hits[k] = self.fileids[k]
            else:
                # Eliminate hits for every non-match
                for fileid in list(hits):
                    if fileid not in entry:
                        del hits[fileid]
        if hits is None:
            return {}
        return list(hits.values())

    segments = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ#_-!"
    def load_index(self, reload=0, wordlist=None):
        # Unless reload is indicated, do not load twice
        if self.index_loaded() and not reload:
            return 0

        # Ok, now let's actually load it
        db = {'WORDS': {}, 'FILES': {'_TOP':(0,None)}, 'FILEIDS': {}}

        # Identify the relevant word-dictionary segments
        if not wordlist:
            segments = self.segments
        else:
            segments = ['-','#']
            for word in wordlist:
                segments.append(word[0].upper())

        # Load the segments
        for segment in segments:
            try:
                f = open(self.indexdb + segment, 'rb')
            except IOError, error:
                # probably just nonexistent segment index file
                if error.errno != errno.ENOENT: raise
            else:
                pickle_str = zlib.decompress(f.read())
                f.close()
                dbslice = marshal.loads(pickle_str)
                if dbslice.get('WORDS'):
                    # if it has some words, add them
                    for word, entry in dbslice['WORDS'].iteritems():
                        db['WORDS'][word] = entry
                if dbslice.get('FILES'):
                    # if it has some files, add them
                    db['FILES'] = dbslice['FILES']
                if dbslice.get('FILEIDS'):
                    # if it has fileids, add them
                    db['FILEIDS'] = dbslice['FILEIDS']

        self.words = db['WORDS']
        self.files = db['FILES']
        self.fileids = db['FILEIDS']
        self.changed = 0

    def save_index(self):
        # only save if the index is loaded and changed
        if not self.index_loaded() or not self.changed:
            return

        # brutal space saver... delete all the small segments
        for segment in self.segments:
            try:
                os.remove(self.indexdb + segment)
            except OSError, error:
                # probably just nonexistent segment index file
                if error.errno != errno.ENOENT: raise

        # First write the much simpler filename/fileid dictionaries
        dbfil = {'WORDS':None, 'FILES':self.files, 'FILEIDS':self.fileids}
        open(self.indexdb+'-','wb').write(zlib.compress(marshal.dumps(dbfil)))

        # The hard part is splitting the word dictionary up, of course
        letters = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ#_"
        segdicts = {}                           # Need batch of empty dicts
        for segment in letters:
            segdicts[segment] = {}
        for word, entry in self.words.iteritems():  # Split into segment dicts
            initchar = word[0].upper()
            segdicts[initchar][word] = entry

        # save
        for initchar in letters:
            db = {'WORDS':segdicts[initchar], 'FILES':None, 'FILEIDS':None}
            pickle_str = marshal.dumps(db)
            filename = self.indexdb + initchar
            pickle_fh = open(filename, 'wb')
            pickle_fh.write(zlib.compress(pickle_str))
            os.chmod(filename, 0664)

        # save done
        self.changed = 0

    def purge_entry(self, identifier):
        '''Remove a file from file index and word index
        '''
        self.load_index()

        if identifier not in self.files:
            return

        file_index = self.files[identifier][0]
        del self.files[identifier]
        del self.fileids[file_index]

        # The much harder part, cleanup the word index
        for key, occurs in self.words.iteritems():
            if file_index in occurs:
                del occurs[file_index]

        # save needed
        self.changed = 1

    def index_loaded(self):
        return (hasattr(self,'fileids') and hasattr(self,'files') and
            hasattr(self,'words'))

    def rollback(self):
        ''' load last saved index info. '''
        self.load_index(reload=1)

    def close(self):
        pass


# vim: set filetype=python ts=4 sw=4 et si
