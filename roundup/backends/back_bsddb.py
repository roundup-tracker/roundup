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
#$Id: back_bsddb.py,v 1.24 2002-09-13 08:20:11 richard Exp $
'''
This module defines a backend that saves the hyperdatabase in BSDDB.
'''

import bsddb, os, marshal
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
            bsddb.btopen(db, 'n')
            db = os.path.join(self.dir, 'journals.%s'%cn)
            bsddb.btopen(db, 'n')

    def getclassdb(self, classname, mode='r'):
        ''' grab a connection to the class db that will be used for
            multiple actions
        '''
        path = os.path.join(os.getcwd(), self.dir, 'nodes.%s'%classname)
        if os.path.exists(path):
            return bsddb.btopen(path, mode)
        else:
            return bsddb.btopen(path, 'c')

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
                print >>hyperdb.DEBUG, "opendb bsddb.open(%r, 'c')"%path
            return bsddb.btopen(path, 'c')

        # open the database with the correct module
        if __debug__:
            print >>hyperdb.DEBUG, "opendb bsddb.open(%r, %r)"%(path, mode)
        return bsddb.btopen(path, mode)

    #
    # Journal
    #
    def getjournal(self, classname, nodeid):
        ''' get the journal for id
        '''
        # attempt to open the journal - in some rare cases, the journal may
        # not exist
        try:
            db = bsddb.btopen(os.path.join(self.dir, 'journals.%s'%classname),
                'r')
        except bsddb.error, error:
            if error.args[0] != 2: raise
            raise IndexError, 'no such %s %s'%(classname, nodeid)
        # more handling of bad journals
        if not db.has_key(nodeid):
            raise IndexError, 'no such %s %s'%(classname, nodeid)
        journal = marshal.loads(db[nodeid])
        res = []
        for entry in journal:
            (nodeid, date_stamp, user, action, params) = entry
            date_obj = date.Date(date_stamp)
            res.append((nodeid, date_obj, user, action, params))
        db.close()
        return res

    def getCachedJournalDB(self, classname):
        ''' get the journal db, looking in our cache of databases for commit
        '''
        # get the database handle
        db_name = 'journals.%s'%classname
        if self.databases.has_key(db_name):
            return self.databases[db_name]
        else:
            db = bsddb.btopen(os.path.join(self.dir, db_name), 'c')
            self.databases[db_name] = db
            return db

