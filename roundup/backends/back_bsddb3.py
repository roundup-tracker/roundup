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
#$Id: back_bsddb3.py,v 1.19.2.1 2003-11-14 00:19:02 richard Exp $
'''
This module defines a backend that saves the hyperdatabase in BSDDB3.
'''

import bsddb3, os, marshal
from roundup import hyperdb, date

# these classes are so similar, we just use the anydbm methods
from back_anydbm import Database, Class, FileClass, IssueClass

#
# Now the database
#
class Database(Database):
    """A database for storing records containing flexible data types."""
    #
    # Class DBs
    #
    def clear(self):
        for cn in self.classes.keys():
            db = os.path.join(self.dir, 'nodes.%s'%cn)
            bsddb3.btopen(db, 'n')
            db = os.path.join(self.dir, 'journals.%s'%cn)
            bsddb3.btopen(db, 'n')

    def getclassdb(self, classname, mode='r'):
        ''' grab a connection to the class db that will be used for
            multiple actions
        '''
        path = os.path.join(os.getcwd(), self.dir, 'nodes.%s'%classname)
        if os.path.exists(path):
            return bsddb3.btopen(path, mode)
        else:
            return bsddb3.btopen(path, 'c')

    def opendb(self, name, mode):
        '''Low-level database opener that gets around anydbm/dbm
           eccentricities.
        '''
        if __debug__:
            print >>hyperdb.DEBUG, self, 'opendb', (self, name, mode)
        # determine which DB wrote the class file
        path = os.path.join(os.getcwd(), self.dir, name)
        if not os.path.exists(path):
            if __debug__:
                print >>hyperdb.DEBUG, "opendb bsddb3.open(%r, 'c')"%path
            return bsddb3.btopen(path, 'c')

        # open the database with the correct module
        if __debug__:
            print >>hyperdb.DEBUG, "opendb bsddb3.open(%r, %r)"%(path, mode)
        return bsddb3.btopen(path, mode)

    #
    # Journal
    #
    def getjournal(self, classname, nodeid):
        ''' get the journal for id

            Raise IndexError if the node doesn't exist (as per history()'s
            API)
        '''
        if __debug__:
            print >>hyperdb.DEBUG, 'getjournal', (self, classname, nodeid)

        # our journal result
        res = []

        # add any journal entries for transactions not committed to the
        # database
        for method, args in self.transactions:
            if method != self.doSaveJournal:
                continue
            (cache_classname, cache_nodeid, cache_action, cache_params,
                cache_creator, cache_creation) = args
            if cache_classname == classname and cache_nodeid == nodeid:
                if not cache_creator:
                    cache_creator = self.curuserid
                if not cache_creation:
                    cache_creation = date.Date()
                res.append((cache_nodeid, cache_creation, cache_creator,
                    cache_action, cache_params))

        # attempt to open the journal - in some rare cases, the journal may
        # not exist
        try:
            db = bsddb3.btopen(os.path.join(self.dir, 'journals.%s'%classname),
                'r')
        except bsddb3._db.DBNoSuchFileError:
            if res:
                # we have unsaved journal entries, return them
                return res
            raise IndexError, 'no such %s %s'%(classname, nodeid)
        # more handling of bad journals
        if not db.has_key(nodeid):
            db.close()
            if res:
                # we have some unsaved journal entries, be happy!
                return res
            raise IndexError, 'no such %s %s'%(classname, nodeid)
        journal = marshal.loads(db[nodeid])
        db.close()

        # add all the saved journal entries for this node
        for nodeid, date_stamp, user, action, params in journal:
            res.append((nodeid, date.Date(date_stamp), user, action, params))
        return res

    def getCachedJournalDB(self, classname):
        ''' get the journal db, looking in our cache of databases for commit
        '''
        # get the database handle
        db_name = 'journals.%s'%classname
        if self.databases.has_key(db_name):
            return self.databases[db_name]
        else:
            db = bsddb3.btopen(os.path.join(self.dir, db_name), 'c')
            self.databases[db_name] = db
            return db

