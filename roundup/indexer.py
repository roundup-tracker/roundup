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
#$Id: indexer.py,v 1.7 2002-07-09 21:38:43 richard Exp $
'''
This module provides an indexer class, RoundupIndexer, that stores text
indices in a roundup instance.  This class makes searching the content of
messages and text files possible.
'''
import os, shutil, re, mimetypes, marshal, zlib, errno

class Indexer:
    ''' Indexes information from roundup's hyperdb to allow efficient
        searching.

        Three structures are created by the indexer:
          files   {identifier: (fileid, wordcount)}
          words   {word: {fileid: count}}
          fileids {fileid: identifier}
    '''
    def __init__(self, db_path):
        self.indexdb_path = os.path.join(db_path, 'indexes')
        self.indexdb = os.path.join(self.indexdb_path, 'index.db')
        self.reindex = 0
        self.quiet = 9
        self.changed = 0

        # see if we need to reindex because of a change in code
        if (not os.path.exists(self.indexdb_path) or
                not os.path.exists(os.path.join(self.indexdb_path, 'version'))):
            # TODO: if the version file exists (in the future) we'll want to
            # check the value in it - for now the file itself is a flag
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
        ''' Add some text associated with the (classname, nodeid, property)
            identifier.
        '''
        # make sure the index is loaded
        self.load_index()

        # remove old entries for this identifier
        if self.files.has_key(identifier):
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

        # save needed
        self.changed = 1

    def splitter(self, text, ftype):
        ''' Split the contents of a text string into a list of 'words'
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
        text = text.upper()

        # Split the raw text, losing anything longer than 25 characters
        # since that'll be gibberish (encoded text or somesuch) or shorter
        # than 3 characters since those short words appear all over the
        # place
        return re.findall(r'\b\w{2,25}\b', text)

    def search(self, search_terms, klass, ignore={},
            dre=re.compile(r'([^\d]+)(\d+)')):
        ''' Display search results looking for [search, terms] associated
            with the hyperdb Class "klass". Ignore hits on {class: property}.

            "dre" is a helper, not an argument.
        '''
        # do the index lookup
        hits = self.find(search_terms)
        if not hits:
            return {}

        # this is specific to "issue" klass ... eugh
        designator_propname = {'msg': 'messages', 'file': 'files'}

        # build a dictionary of nodes and their associated messages
        # and files
        nodeids = {}
        for classname, nodeid, property in hits.values():
            # skip this result if we don't care about this class/property
            if ignore.has_key((classname, property)):
                continue

            # if it's a property on klass, it's easy
            if classname == klass.classname:
                if not nodeids.has_key(nodeid):
                    nodeids[nodeid] = {}
                continue

            # it's a linked class - find the klass entries that are
            # linked to it
            linkprop = designator_propname[classname]
            for resid in klass.find(**{linkprop: nodeid}):
                resid = str(resid)
                if not nodeids.has_key(id):
                    nodeids[resid] = {}

                # update the links for this klass nodeid
                node_dict = nodeids[resid]
                if not node_dict.has_key(linkprop):
                    node_dict[linkprop] = [nodeid]
                elif node_dict.has_key(linkprop):
                    node_dict[linkprop].append(nodeid)
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
        self.changed = 0

    def save_index(self):
        # only save if the index is loaded and changed
        if not self.index_loaded() or not self.changed:
            return

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
        letters = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ#_"
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

        # save done
        self.changed = 0

    def purge_entry(self, identifier):
        ''' Remove a file from file index and word index
        '''
        if not self.files.has_key(identifier):
            return

        file_index = self.files[identifier][0]
        del self.files[identifier]
        del self.fileids[file_index]

        # The much harder part, cleanup the word index
        for key, occurs in self.words.items():
            if occurs.has_key(file_index):
                del occurs[file_index]

        # save needed
        self.changed = 1

    def index_loaded(self):
        return (hasattr(self,'fileids') and hasattr(self,'files') and
            hasattr(self,'words'))

#
#$Log: not supported by cvs2svn $
#Revision 1.6  2002/07/09 04:26:44  richard
#We're indexing numbers now, and _underscore words
#
#Revision 1.5  2002/07/09 04:19:09  richard
#Added reindex command to roundup-admin.
#Fixed reindex on first access.
#Also fixed reindexing of entries that change.
#
#Revision 1.4  2002/07/09 03:02:52  richard
#More indexer work:
#- all String properties may now be indexed too. Currently there's a bit of
#  "issue" specific code in the actual searching which needs to be
#  addressed. In a nutshell:
#  + pass 'indexme="yes"' as a String() property initialisation arg, eg:
#        file = FileClass(db, "file", name=String(), type=String(),
#            comment=String(indexme="yes"))
#  + the comment will then be indexed and be searchable, with the results
#    related back to the issue that the file is linked to
#- as a result of this work, the FileClass has a default MIME type that may
#  be overridden in a subclass, or by the use of a "type" property as is
#  done in the default templates.
#- the regeneration of the indexes (if necessary) is done once the schema is
#  set up in the dbinit.
#
#Revision 1.3  2002/07/08 06:58:15  richard
#cleaned up the indexer code:
# - it splits more words out (much simpler, faster splitter)
# - removed code we'll never use (roundup.roundup_indexer has the full
#   implementation, and replaces roundup.indexer)
# - only index text/plain and rfc822/message (ideas for other text formats to
#   index are welcome)
# - added simple unit test for indexer. Needs more tests for regression.
#
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
