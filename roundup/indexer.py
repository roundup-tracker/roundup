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
#$Id: indexer.py,v 1.3 2002-07-08 06:58:15 richard Exp $
'''
This module provides an indexer class, RoundupIndexer, that stores text
indices in a roundup instance.  This class makes searching the content of
messages and text files possible.
'''
import os, shutil, re, mimetypes, marshal, zlib, errno

class Indexer:
    ''' Indexes messages and files.

        This implements a new splitter based on re.findall '\w+' and the
        add_othertext method.
    '''
    def __init__(self, db_path):
        indexdb_path = os.path.join(db_path, 'indexes')

        # see if we need to reindex because of a change in code
        if (os.path.exists(indexdb_path) and
                not os.path.exists(os.path.join(indexdb_path, 'version'))):
            shutil.rmtree(indexdb_path)

        # see if the index exists
        index_exists = 0
        if not os.path.exists(indexdb_path):
            os.makedirs(indexdb_path)
            os.chmod(indexdb_path, 0775)
            open(os.path.join(indexdb_path, 'version'), 'w').write('1\n')
        else:
            index_exists = 1

        # save off the path to the indexdb
        self.indexdb = os.path.join(indexdb_path, 'index.db')
        self.reindex = 0
        self.casesensitive = 0
        self.quiet = 9

        if not index_exists:
            # index everything
            files_path = os.path.join(db_path, 'files')
            self.add_files(dir=files_path)
            self.save_index()

    # override add_files so it's a little smarter about file types
    def add_files(self, dir):
        if not hasattr(self, 'files'):
            self.load_index()
        os.path.walk(dir, self.walk_add_file, None)
        # Rebuild the fileid index
        self.fileids = {}
        for fname in self.files.keys():
            fileid = self.files[fname][0]
            self.fileids[fileid] = fname

    # override add_file so it can be a little smarter about determining the
    # file type
    def walk_add_file(self, arg, dname, names, ftype=None):
        for name in names:
            name = os.path.join(dname, name)
            if os.path.isfile(name):
                self.add_file(name)
            elif os.path.isdir(name):
                os.path.walk(name, self.walk_add_file, None)
    def add_file(self, fname, ftype=None):
        ''' Index the contents of a regular file
        '''
        if not hasattr(self, 'files'):
            self.load_index()
        # Is file eligible for (re)indexing?
        if self.files.has_key(fname):
            if self.reindex:
                # Reindexing enabled, cleanup dicts
                self.purge_entry(fname, self.files, self.words)
            else:
                # DO NOT reindex this file
                if self.quiet < 5:
                    print "Skipping", fname
                return 0

        # guess the file type
        if ftype is None:
            ftype = mimetypes.guess_type(fname)

        # read in the file
        text = open(fname).read()
        if self.quiet < 5: print "Indexing", fname
        words = self.splitter(text, ftype)

        # Find new file index, and assign it to filename
        # (_TOP uses trick of negative to avoid conflict with file index)
        self.files['_TOP'] = (self.files['_TOP'][0]-1, None)
        file_index =  abs(self.files['_TOP'][0])
        self.files[fname] = (file_index, len(words))

        filedict = {}
        for word in words:
            if filedict.has_key(word):
                filedict[word] = filedict[word]+1
            else:
                filedict[word] = 1

        for word in filedict.keys():
            if self.words.has_key(word):
                entry = self.words[word]
            else:
                entry = {}
            entry[file_index] = filedict[word]
            self.words[word] = entry

    # NOTE: this method signature deviates from the one specified in
    # indexer - I'm not entirely sure where it was expected to the text
    # from otherwise...
    def add_othertext(self, identifier, text):
        ''' Add some text associated with the identifier
        '''
        # Is file eligible for (re)indexing?
        if self.files.has_key(identifier):
            # Reindexing enabled, cleanup dicts
            if self.reindex:
                self.purge_entry(identifier, self.files, self.words)
            else:
                # DO NOT reindex this file
                if self.quiet < 5:
                    print "Not reindexing", identifier
                return 0

        # split into words
        words = self.splitter(text, 'text/plain')

        # Find new file index, and assign it to identifier
        # (_TOP uses trick of negative to avoid conflict with file index)
        self.files['_TOP'] = (self.files['_TOP'][0]-1, None)
        file_index = abs(self.files['_TOP'][0])
        self.files[identifier] = (file_index, len(words))
        self.fileids[file_index] = identifier

        # find the unique words
        filedict = {}
        for word in words:
            if filedict.has_key(word):
                filedict[word] = filedict[word]+1
            else:
                filedict[word] = 1

        # now add to the totals
        for word in filedict.keys():
            # each word has a dict of {identifier: count}
            if self.words.has_key(word):
                entry = self.words[word]
            else:
                # new word
                entry = {}
                self.words[word] = entry

            # make a reference to the file for this word
            entry[file_index] = filedict[word]

    def splitter(self, text, ftype):
        ''' Split the contents of a text string into a list of 'words'
        '''
        if ftype in ('text/plain', 'message/rfc822'):
            words = self.text_splitter(text, self.casesensitive)
        else:
            return []
        return words

    def text_splitter(self, text, casesensitive=0):
        """Split text/plain string into a list of words
        """
        # Let's adjust case if not case-sensitive
        if not casesensitive:
            text = text.upper()

        # Split the raw text, losing anything longer than 25 characters
        # since that'll be gibberish (encoded text or somesuch) or shorter
        # than 3 characters since those short words appear all over the
        # place
        return re.findall(r'\b\w{2,25}\b', text)

    def search(self, search_terms, klass):
        ''' display search results
        '''
        hits = self.find(search_terms)
        links = []
        nodeids = {}
        designator_propname = {'msg': 'messages', 'file': 'files'}
        if hits:
            hitcount = len(hits)
            # build a dictionary of nodes and their associated messages
            # and files
            for hit in hits.keys():
                filename = hits[hit].split('/')[-1]
                for designator, propname in designator_propname.items():
                    if not filename.startswith(designator):
                        continue
                    nodeid = filename[len(designator):]
                    result = apply(klass.find, (), {propname:nodeid})
                    if not result:
                        continue

                    id = str(result[0])
                    if not nodeids.has_key(id):
                        nodeids[id] = {}

                    node_dict = nodeids[id]
                    if not node_dict.has_key(propname):
                        node_dict[propname] = [nodeid]
                    elif node_dict.has_key(propname):
                        node_dict[propname].append(nodeid)

        return nodeids

    # we override this to ignore not 2 < word < 25 and also to fix a bug -
    # the (fail) case.
    def find(self, wordlist):
        ''' Locate files that match ALL the words in wordlist
        '''
        if not hasattr(self, 'words'):
            self.load_index()
        self.load_index(wordlist=wordlist)
        entries = {}
        hits = None
        for word in wordlist:
            if not 2 < len(word) < 25:
                # word outside the bounds of what we index - ignore
                continue
            if not self.casesensitive:
                word = word.upper()
            entry = self.words.get(word)    # For each word, get index
            entries[word] = entry           #   of matching files
            if not entry:                   # Nothing for this one word (fail)
                return {}
            if hits is None:
                hits = {}
                for k in entry.keys():
                    hits[k] = self.fileids[k]
            else:
                # Eliminate hits for every non-match
                for fileid in hits.keys():
                    if not entry.has_key(fileid):
                        del hits[fileid]
        if hits is None:
            return {}
        return hits

    segments = "ABCDEFGHIJKLMNOPQRSTUVWXYZ#-!"
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
                if error.errno != errno.ENOENT:
                    raise
            else:
                pickle_str = zlib.decompress(f.read())
                f.close()
                dbslice = marshal.loads(pickle_str)
                if dbslice.get('WORDS'):
                    # if it has some words, add them
                    for word, entry in dbslice['WORDS'].items():
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

    def save_index(self):
        # brutal space saver... delete all the small segments
        for segment in self.segments:
            try:
                os.remove(self.indexdb + segment)
            except OSError:
                # probably just nonexistent segment index file
                # TODO: make sure it's an EEXIST
                pass

        # First write the much simpler filename/fileid dictionaries
        dbfil = {'WORDS':None, 'FILES':self.files, 'FILEIDS':self.fileids}
        open(self.indexdb+'-','wb').write(zlib.compress(marshal.dumps(dbfil)))

        # The hard part is splitting the word dictionary up, of course
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ#"
        segdicts = {}                           # Need batch of empty dicts
        for segment in letters:
            segdicts[segment] = {}
        for word, entry in self.words.items():  # Split into segment dicts
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

    def purge_entry(self, fname, file_dct, word_dct):
        ''' Remove a file from file index and word index
        '''
        try:        # The easy part, cleanup the file index
            file_index = file_dct[fname]
            del file_dct[fname]
        except KeyError:
            pass    # We'll assume we only encounter KeyError's
        # The much harder part, cleanup the word index
        for word, occurs in word_dct.items():
            if occurs.has_key(file_index):
                del occurs[file_index]
                word_dct[word] = occurs

    def index_loaded(self):
        return (hasattr(self,'fileids') and hasattr(self,'files') and
            hasattr(self,'words'))

#
#$Log: not supported by cvs2svn $
#Revision 1.2  2002/05/25 07:16:24  rochecompaan
#Merged search_indexing-branch with HEAD
#
#Revision 1.1.2.3  2002/05/02 11:52:12  rochecompaan
#Fixed small bug that prevented indexes from being generated.
#
#Revision 1.1.2.2  2002/04/19 19:54:42  rochecompaan
#cgi_client.py
#    removed search link for the time being
#    moved rendering of matches to htmltemplate
#hyperdb.py
#    filtering of nodes on full text search incorporated in filter method
#roundupdb.py
#    added paramater to call of filter method
#roundup_indexer.py
#    added search method to RoundupIndexer class
#
#Revision 1.1.2.1  2002/04/03 11:55:57  rochecompaan
# . Added feature #526730 - search for messages capability
#
