#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
#$Id: back_anydbm.py,v 1.39 2002-07-09 03:02:52 richard Exp $
'''
This module defines a backend that saves the hyperdatabase in a database
chosen by anydbm. It is guaranteed to always be available in python
versions >2.1.1 (the dumbdbm fallback in 2.1.1 and earlier has several
serious bugs, and is not available)
'''

import whichdb, anydbm, os, marshal
from roundup import hyperdb, date
from blobfiles import FileStorage
from roundup.indexer import Indexer
from locking import acquire_lock, release_lock

#
# Now the database
#
class Database(FileStorage, hyperdb.Database):
    """A database for storing records containing flexible data types.

    Transaction stuff TODO:
        . check the timestamp of the class file and nuke the cache if it's
          modified. Do some sort of conflict checking on the dirty stuff.
        . perhaps detect write collisions (related to above)?

    """
    def __init__(self, config, journaltag=None):
        """Open a hyperdatabase given a specifier to some storage.

        The 'storagelocator' is obtained from config.DATABASE.
        The meaning of 'storagelocator' depends on the particular
        implementation of the hyperdatabase.  It could be a file name,
        a directory path, a socket descriptor for a connection to a
        database over the network, etc.

        The 'journaltag' is a token that will be attached to the journal
        entries for any edits done on the database.  If 'journaltag' is
        None, the database is opened in read-only mode: the Class.create(),
        Class.set(), and Class.retire() methods are disabled.
        """
        self.config, self.journaltag = config, journaltag
        self.dir = config.DATABASE
        self.classes = {}
        self.cache = {}         # cache of nodes loaded or created
        self.dirtynodes = {}    # keep track of the dirty nodes by class
        self.newnodes = {}      # keep track of the new nodes by class
        self.transactions = []
        self.indexer = Indexer(self.dir)
        # ensure files are group readable and writable
        os.umask(0002)

    def post_init(self):
        """Called once the schema initialisation has finished."""
        # reindex the db if necessary
        if not self.indexer.should_reindex():
            return
        for klass in self.classes.values():
            for nodeid in klass.list():
                klass.index(nodeid)
        self.indexer.save_index()

    def __repr__(self):
        return '<back_anydbm instance at %x>'%id(self) 

    #
    # Classes
    #
    def __getattr__(self, classname):
        """A convenient way of calling self.getclass(classname)."""
        if self.classes.has_key(classname):
            if __debug__:
                print >>hyperdb.DEBUG, '__getattr__', (self, classname)
            return self.classes[classname]
        raise AttributeError, classname

    def addclass(self, cl):
        if __debug__:
            print >>hyperdb.DEBUG, 'addclass', (self, cl)
        cn = cl.classname
        if self.classes.has_key(cn):
            raise ValueError, cn
        self.classes[cn] = cl

    def getclasses(self):
        """Return a list of the names of all existing classes."""
        if __debug__:
            print >>hyperdb.DEBUG, 'getclasses', (self,)
        l = self.classes.keys()
        l.sort()
        return l

    def getclass(self, classname):
        """Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        """
        if __debug__:
            print >>hyperdb.DEBUG, 'getclass', (self, classname)
        return self.classes[classname]

    #
    # Class DBs
    #
    def clear(self):
        '''Delete all database contents
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'clear', (self,)
        for cn in self.classes.keys():
            for dummy in 'nodes', 'journals':
                path = os.path.join(self.dir, 'journals.%s'%cn)
                if os.path.exists(path):
                    os.remove(path)
                elif os.path.exists(path+'.db'):    # dbm appends .db
                    os.remove(path+'.db')

    def getclassdb(self, classname, mode='r'):
        ''' grab a connection to the class db that will be used for
            multiple actions
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'getclassdb', (self, classname, mode)
        return self._opendb('nodes.%s'%classname, mode)

    def _opendb(self, name, mode):
        '''Low-level database opener that gets around anydbm/dbm
           eccentricities.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, '_opendb', (self, name, mode)

        # determine which DB wrote the class file
        db_type = ''
        path = os.path.join(os.getcwd(), self.dir, name)
        if os.path.exists(path):
            db_type = whichdb.whichdb(path)
            if not db_type:
                raise hyperdb.DatabaseError, "Couldn't identify database type"
        elif os.path.exists(path+'.db'):
            # if the path ends in '.db', it's a dbm database, whether
            # anydbm says it's dbhash or not!
            db_type = 'dbm'

        # new database? let anydbm pick the best dbm
        if not db_type:
            if __debug__:
                print >>hyperdb.DEBUG, "_opendb anydbm.open(%r, 'n')"%path
            return anydbm.open(path, 'n')

        # open the database with the correct module
        try:
            dbm = __import__(db_type)
        except ImportError:
            raise hyperdb.DatabaseError, \
                "Couldn't open database - the required module '%s'"\
                " is not available"%db_type
        if __debug__:
            print >>hyperdb.DEBUG, "_opendb %r.open(%r, %r)"%(db_type, path,
                mode)
        return dbm.open(path, mode)

    def _lockdb(self, name):
        ''' Lock a database file
        '''
        path = os.path.join(os.getcwd(), self.dir, '%s.lock'%name)
        return acquire_lock(path)

    #
    # Node IDs
    #
    def newid(self, classname):
        ''' Generate a new id for the given class
        '''
        # open the ids DB - create if if doesn't exist
        lock = self._lockdb('_ids')
        db = self._opendb('_ids', 'c')
        if db.has_key(classname):
            newid = db[classname] = str(int(db[classname]) + 1)
        else:
            # the count() bit is transitional - older dbs won't start at 1
            newid = str(self.getclass(classname).count()+1)
            db[classname] = newid
        db.close()
        release_lock(lock)
        return newid

    #
    # Nodes
    #
    def addnode(self, classname, nodeid, node):
        ''' add the specified node to its class's db
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'addnode', (self, classname, nodeid, node)
        self.newnodes.setdefault(classname, {})[nodeid] = 1
        self.cache.setdefault(classname, {})[nodeid] = node
        self.savenode(classname, nodeid, node)

    def setnode(self, classname, nodeid, node):
        ''' change the specified node
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'setnode', (self, classname, nodeid, node)
        self.dirtynodes.setdefault(classname, {})[nodeid] = 1

        # can't set without having already loaded the node
        self.cache[classname][nodeid] = node
        self.savenode(classname, nodeid, node)

    def savenode(self, classname, nodeid, node):
        ''' perform the saving of data specified by the set/addnode
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'savenode', (self, classname, nodeid, node)
        self.transactions.append((self._doSaveNode, (classname, nodeid, node)))

    def getnode(self, classname, nodeid, db=None, cache=1):
        ''' get a node from the database
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'getnode', (self, classname, nodeid, db)
        if cache:
            # try the cache
            cache_dict = self.cache.setdefault(classname, {})
            if cache_dict.has_key(nodeid):
                if __debug__:
                    print >>hyperdb.TRACE, 'get %s %s cached'%(classname,
                        nodeid)
                return cache_dict[nodeid]

        if __debug__:
            print >>hyperdb.TRACE, 'get %s %s'%(classname, nodeid)

        # get from the database and save in the cache
        if db is None:
            db = self.getclassdb(classname)
        if not db.has_key(nodeid):
            raise IndexError, "no such %s %s"%(classname, nodeid)

        # decode
        res = marshal.loads(db[nodeid])

        # reverse the serialisation
        res = self.unserialise(classname, res)

        # store off in the cache dict
        if cache:
            cache_dict[nodeid] = res

        return res

    def hasnode(self, classname, nodeid, db=None):
        ''' determine if the database has a given node
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'hasnode', (self, classname, nodeid, db)

        # try the cache
        cache = self.cache.setdefault(classname, {})
        if cache.has_key(nodeid):
            if __debug__:
                print >>hyperdb.TRACE, 'has %s %s cached'%(classname, nodeid)
            return 1
        if __debug__:
            print >>hyperdb.TRACE, 'has %s %s'%(classname, nodeid)

        # not in the cache - check the database
        if db is None:
            db = self.getclassdb(classname)
        res = db.has_key(nodeid)
        return res

    def countnodes(self, classname, db=None):
        if __debug__:
            print >>hyperdb.DEBUG, 'countnodes', (self, classname, db)
        # include the new nodes not saved to the DB yet
        count = len(self.newnodes.get(classname, {}))

        # and count those in the DB
        if db is None:
            db = self.getclassdb(classname)
        count = count + len(db.keys())
        return count

    def getnodeids(self, classname, db=None):
        if __debug__:
            print >>hyperdb.DEBUG, 'getnodeids', (self, classname, db)
        # start off with the new nodes
        res = self.newnodes.get(classname, {}).keys()

        if db is None:
            db = self.getclassdb(classname)
        res = res + db.keys()
        return res


    #
    # Files - special node properties
    # inherited from FileStorage

    #
    # Journal
    #
    def addjournal(self, classname, nodeid, action, params):
        ''' Journal the Action
        'action' may be:

            'create' or 'set' -- 'params' is a dictionary of property values
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retire' -- 'params' is None
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'addjournal', (self, classname, nodeid,
                action, params)
        self.transactions.append((self._doSaveJournal, (classname, nodeid,
            action, params)))

    def getjournal(self, classname, nodeid):
        ''' get the journal for id
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'getjournal', (self, classname, nodeid)
        # attempt to open the journal - in some rare cases, the journal may
        # not exist
        try:
            db = self._opendb('journals.%s'%classname, 'r')
        except anydbm.error, error:
            if str(error) == "need 'c' or 'n' flag to open new db": return []
            elif error.args[0] != 2: raise
            return []
        try:
            journal = marshal.loads(db[nodeid])
        except KeyError:
            raise KeyError, 'no such %s %s'%(classname, nodeid)
        res = []
        for entry in journal:
            (nodeid, date_stamp, user, action, params) = entry
            date_obj = date.Date(date_stamp)
            res.append((nodeid, date_obj, user, action, params))
        return res

    def pack(self, pack_before):
        ''' delete all journal entries before 'pack_before' '''
        if __debug__:
            print >>hyperdb.DEBUG, 'packjournal', (self, pack_before)

        pack_before = pack_before.get_tuple()

        classes = self.getclasses()

        # TODO: factor this out to method - we're already doing it in
        # _opendb.
        db_type = ''
        path = os.path.join(os.getcwd(), self.dir, classes[0])
        if os.path.exists(path):
            db_type = whichdb.whichdb(path)
            if not db_type:
                raise hyperdb.DatabaseError, "Couldn't identify database type"
        elif os.path.exists(path+'.db'):
            db_type = 'dbm'

        for classname in classes:
            db_name = 'journals.%s'%classname
            db = self._opendb(db_name, 'w')

            for key in db.keys():
                journal = marshal.loads(db[key])
                l = []
                last_set_entry = None
                for entry in journal:
                    (nodeid, date_stamp, self.journaltag, action, 
                        params) = entry
                    if date_stamp > pack_before or action == 'create':
                        l.append(entry)
                    elif action == 'set':
                        # grab the last set entry to keep information on
                        # activity
                        last_set_entry = entry
                if last_set_entry:
                    date_stamp = last_set_entry[1]
                    # if the last set entry was made after the pack date
                    # then it is already in the list
                    if date_stamp < pack_before:
                        l.append(last_set_entry)
                db[key] = marshal.dumps(l)
            if db_type == 'gdbm':
                db.reorganize()
            db.close()
            

    #
    # Basic transaction support
    #
    def commit(self):
        ''' Commit the current transactions.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'commit', (self,)
        # TODO: lock the DB

        # keep a handle to all the database files opened
        self.databases = {}

        # now, do all the transactions
        reindex = {}
        for method, args in self.transactions:
            reindex[method(*args)] = 1

        # now close all the database files
        for db in self.databases.values():
            db.close()
        del self.databases
        # TODO: unlock the DB

        # reindex the nodes that request it
        for classname, nodeid in filter(None, reindex.keys()):
            print >>hyperdb.DEBUG, 'commit.reindex', (classname, nodeid)
            self.getclass(classname).index(nodeid)

        # save the indexer state
        self.indexer.save_index()

        # all transactions committed, back to normal
        self.cache = {}
        self.dirtynodes = {}
        self.newnodes = {}
        self.transactions = []

    def _doSaveNode(self, classname, nodeid, node):
        if __debug__:
            print >>hyperdb.DEBUG, '_doSaveNode', (self, classname, nodeid,
                node)

        # get the database handle
        db_name = 'nodes.%s'%classname
        if self.databases.has_key(db_name):
            db = self.databases[db_name]
        else:
            db = self.databases[db_name] = self.getclassdb(classname, 'c')

        # now save the marshalled data
        db[nodeid] = marshal.dumps(self.serialise(classname, node))

        # return the classname, nodeid so we reindex this content
        return (classname, nodeid)

    def _doSaveJournal(self, classname, nodeid, action, params):
        # serialise first
        if action in ('set', 'create'):
            params = self.serialise(classname, params)

        # create the journal entry
        entry = (nodeid, date.Date().get_tuple(), self.journaltag, action,
            params)

        if __debug__:
            print >>hyperdb.DEBUG, '_doSaveJournal', entry

        # get the database handle
        db_name = 'journals.%s'%classname
        if self.databases.has_key(db_name):
            db = self.databases[db_name]
        else:
            db = self.databases[db_name] = self._opendb(db_name, 'c')

        # now insert the journal entry
        if db.has_key(nodeid):
            # append to existing
            s = db[nodeid]
            l = marshal.loads(s)
            l.append(entry)
        else:
            l = [entry]

        db[nodeid] = marshal.dumps(l)

    def rollback(self):
        ''' Reverse all actions from the current transaction.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'rollback', (self, )
        for method, args in self.transactions:
            # delete temporary files
            if method == self._doStoreFile:
                self._rollbackStoreFile(*args)
        self.cache = {}
        self.dirtynodes = {}
        self.newnodes = {}
        self.transactions = []

#
#$Log: not supported by cvs2svn $
#Revision 1.38  2002/07/08 06:58:15  richard
#cleaned up the indexer code:
# - it splits more words out (much simpler, faster splitter)
# - removed code we'll never use (roundup.roundup_indexer has the full
#   implementation, and replaces roundup.indexer)
# - only index text/plain and rfc822/message (ideas for other text formats to
#   index are welcome)
# - added simple unit test for indexer. Needs more tests for regression.
#
#Revision 1.37  2002/06/20 23:52:35  richard
#More informative error message
#
#Revision 1.36  2002/06/19 03:07:19  richard
#Moved the file storage commit into blobfiles where it belongs.
#
#Revision 1.35  2002/05/25 07:16:24  rochecompaan
#Merged search_indexing-branch with HEAD
#
#Revision 1.34  2002/05/15 06:21:21  richard
# . node caching now works, and gives a small boost in performance
#
#As a part of this, I cleaned up the DEBUG output and implemented TRACE
#output (HYPERDBTRACE='file to trace to') with checkpoints at the start of
#CGI requests. Run roundup with python -O to skip all the DEBUG/TRACE stuff
#(using if __debug__ which is compiled out with -O)
#
#Revision 1.33  2002/04/24 10:38:26  rochecompaan
#All database files are now created group readable and writable.
#
#Revision 1.32  2002/04/15 23:25:15  richard
#. node ids are now generated from a lockable store - no more race conditions
#
#We're using the portalocker code by Jonathan Feinberg that was contributed
#to the ASPN Python cookbook. This gives us locking across Unix and Windows.
#
#Revision 1.31  2002/04/03 05:54:31  richard
#Fixed serialisation problem by moving the serialisation step out of the
#hyperdb.Class (get, set) into the hyperdb.Database.
#
#Also fixed htmltemplate after the showid changes I made yesterday.
#
#Unit tests for all of the above written.
#
#Revision 1.30.2.1  2002/04/03 11:55:57  rochecompaan
# . Added feature #526730 - search for messages capability
#
#Revision 1.30  2002/02/27 03:40:59  richard
#Ran it through pychecker, made fixes
#
#Revision 1.29  2002/02/25 14:34:31  grubert
# . use blobfiles in back_anydbm which is used in back_bsddb.
#   change test_db as dirlist does not work for subdirectories.
#   ATTENTION: blobfiles now creates subdirectories for files.
#
#Revision 1.28  2002/02/16 09:14:17  richard
# . #514854 ] History: "User" is always ticket creator
#
#Revision 1.27  2002/01/22 07:21:13  richard
#. fixed back_bsddb so it passed the journal tests
#
#... it didn't seem happy using the back_anydbm _open method, which is odd.
#Yet another occurrance of whichdb not being able to recognise older bsddb
#databases. Yadda yadda. Made the HYPERDBDEBUG stuff more sane in the
#process.
#
#Revision 1.26  2002/01/22 05:18:38  rochecompaan
#last_set_entry was referenced before assignment
#
#Revision 1.25  2002/01/22 05:06:08  rochecompaan
#We need to keep the last 'set' entry in the journal to preserve
#information on 'activity' for nodes.
#
#Revision 1.24  2002/01/21 16:33:20  rochecompaan
#You can now use the roundup-admin tool to pack the database
#
#Revision 1.23  2002/01/18 04:32:04  richard
#Rollback was breaking because a message hadn't actually been written to the file. Needs
#more investigation.
#
#Revision 1.22  2002/01/14 02:20:15  richard
# . changed all config accesses so they access either the instance or the
#   config attriubute on the db. This means that all config is obtained from
#   instance_config instead of the mish-mash of classes. This will make
#   switching to a ConfigParser setup easier too, I hope.
#
#At a minimum, this makes migration a _little_ easier (a lot easier in the
#0.5.0 switch, I hope!)
#
#Revision 1.21  2002/01/02 02:31:38  richard
#Sorry for the huge checkin message - I was only intending to implement #496356
#but I found a number of places where things had been broken by transactions:
# . modified ROUNDUPDBSENDMAILDEBUG to be SENDMAILDEBUG and hold a filename
#   for _all_ roundup-generated smtp messages to be sent to.
# . the transaction cache had broken the roundupdb.Class set() reactors
# . newly-created author users in the mailgw weren't being committed to the db
#
#Stuff that made it into CHANGES.txt (ie. the stuff I was actually working
#on when I found that stuff :):
# . #496356 ] Use threading in messages
# . detectors were being registered multiple times
# . added tests for mailgw
# . much better attaching of erroneous messages in the mail gateway
#
#Revision 1.20  2001/12/18 15:30:34  rochecompaan
#Fixed bugs:
# .  Fixed file creation and retrieval in same transaction in anydbm
#    backend
# .  Cgi interface now renders new issue after issue creation
# .  Could not set issue status to resolved through cgi interface
# .  Mail gateway was changing status back to 'chatting' if status was
#    omitted as an argument
#
#Revision 1.19  2001/12/17 03:52:48  richard
#Implemented file store rollback. As a bonus, the hyperdb is now capable of
#storing more than one file per node - if a property name is supplied,
#the file is called designator.property.
#I decided not to migrate the existing files stored over to the new naming
#scheme - the FileClass just doesn't specify the property name.
#
#Revision 1.18  2001/12/16 10:53:38  richard
#take a copy of the node dict so that the subsequent set
#operation doesn't modify the oldvalues structure
#
#Revision 1.17  2001/12/14 23:42:57  richard
#yuck, a gdbm instance tests false :(
#I've left the debugging code in - it should be removed one day if we're ever
#_really_ anal about performace :)
#
#Revision 1.16  2001/12/12 03:23:14  richard
#Cor blimey this anydbm/whichdb stuff is yecchy. Turns out that whichdb
#incorrectly identifies a dbm file as a dbhash file on my system. This has
#been submitted to the python bug tracker as issue #491888:
#https://sourceforge.net/tracker/index.php?func=detail&aid=491888&group_id=5470&atid=105470
#
#Revision 1.15  2001/12/12 02:30:51  richard
#I fixed the problems with people whose anydbm was using the dbm module at the
#backend. It turns out the dbm module modifies the file name to append ".db"
#and my check to determine if we're opening an existing or new db just
#tested os.path.exists() on the filename. Well, no longer! We now perform a
#much better check _and_ cope with the anydbm implementation module changing
#too!
#I also fixed the backends __init__ so only ImportError is squashed.
#
#Revision 1.14  2001/12/10 22:20:01  richard
#Enabled transaction support in the bsddb backend. It uses the anydbm code
#where possible, only replacing methods where the db is opened (it uses the
#btree opener specifically.)
#Also cleaned up some change note generation.
#Made the backends package work with pydoc too.
#
#Revision 1.13  2001/12/02 05:06:16  richard
#. We now use weakrefs in the Classes to keep the database reference, so
#  the close() method on the database is no longer needed.
#  I bumped the minimum python requirement up to 2.1 accordingly.
#. #487480 ] roundup-server
#. #487476 ] INSTALL.txt
#
#I also cleaned up the change message / post-edit stuff in the cgi client.
#There's now a clearly marked "TODO: append the change note" where I believe
#the change note should be added there. The "changes" list will obviously
#have to be modified to be a dict of the changes, or somesuch.
#
#More testing needed.
#
#Revision 1.12  2001/12/01 07:17:50  richard
#. We now have basic transaction support! Information is only written to
#  the database when the commit() method is called. Only the anydbm
#  backend is modified in this way - neither of the bsddb backends have been.
#  The mail, admin and cgi interfaces all use commit (except the admin tool
#  doesn't have a commit command, so interactive users can't commit...)
#. Fixed login/registration forwarding the user to the right page (or not,
#  on a failure)
#
#Revision 1.11  2001/11/21 02:34:18  richard
#Added a target version field to the extended issue schema
#
#Revision 1.10  2001/10/09 23:58:10  richard
#Moved the data stringification up into the hyperdb.Class class' get, set
#and create methods. This means that the data is also stringified for the
#journal call, and removes duplication of code from the backends. The
#backend code now only sees strings.
#
#Revision 1.9  2001/10/09 07:25:59  richard
#Added the Password property type. See "pydoc roundup.password" for
#implementation details. Have updated some of the documentation too.
#
#Revision 1.8  2001/09/29 13:27:00  richard
#CGI interfaces now spit up a top-level index of all the instances they can
#serve.
#
#Revision 1.7  2001/08/12 06:32:36  richard
#using isinstance(blah, Foo) now instead of isFooType
#
#Revision 1.6  2001/08/07 00:24:42  richard
#stupid typo
#
#Revision 1.5  2001/08/07 00:15:51  richard
#Added the copyright/license notice to (nearly) all files at request of
#Bizar Software.
#
#Revision 1.4  2001/07/30 01:41:36  richard
#Makes schema changes mucho easier.
#
#Revision 1.3  2001/07/25 01:23:07  richard
#Added the Roundup spec to the new documentation directory.
#
#Revision 1.2  2001/07/23 08:20:44  richard
#Moved over to using marshal in the bsddb and anydbm backends.
#roundup-admin now has a "freshen" command that'll load/save all nodes (not
# retired - mod hyperdb.Class.list() so it lists retired nodes)
#
#
