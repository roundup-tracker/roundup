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
#$Id: back_bsddb.py,v 1.21 2002-09-03 07:33:01 richard Exp $
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
            return bsddb.btopen(path, 'n')

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

    def doSaveJournal(self, classname, nodeid, action, params):
        # serialise first
        if action in ('set', 'create'):
            params = self.serialise(classname, params)

        entry = (nodeid, date.Date().get_tuple(), self.journaltag, action,
            params)

        if __debug__:
            print >>hyperdb.DEBUG, 'doSaveJournal', entry

        db = self.getCachedJournalDB(classname)

        if db.has_key(nodeid):
            s = db[nodeid]
            l = marshal.loads(s)
            l.append(entry)
        else:
            l = [entry]

        db[nodeid] = marshal.dumps(l)

#
#$Log: not supported by cvs2svn $
#Revision 1.20  2002/07/19 03:36:34  richard
#Implemented the destroy() method needed by the session database (and possibly
#others). At the same time, I removed the leading underscores from the hyperdb
#methods that Really Didn't Need Them.
#The journal also raises IndexError now for all situations where there is a
#request for the journal of a node that doesn't have one. It used to return
#[] in _some_ situations, but not all. This _may_ break code, but the tests
#pass...
#
#Revision 1.19  2002/07/14 02:05:53  richard
#. all storage-specific code (ie. backend) is now implemented by the backends
#
#Revision 1.18  2002/05/15 06:21:21  richard
# . node caching now works, and gives a small boost in performance
#
#As a part of this, I cleaned up the DEBUG output and implemented TRACE
#output (HYPERDBTRACE='file to trace to') with checkpoints at the start of
#CGI requests. Run roundup with python -O to skip all the DEBUG/TRACE stuff
#(using if __debug__ which is compiled out with -O)
#
#Revision 1.17  2002/04/03 05:54:31  richard
#Fixed serialisation problem by moving the serialisation step out of the
#hyperdb.Class (get, set) into the hyperdb.Database.
#
#Also fixed htmltemplate after the showid changes I made yesterday.
#
#Unit tests for all of the above written.
#
#Revision 1.16  2002/02/27 03:40:59  richard
#Ran it through pychecker, made fixes
#
#Revision 1.15  2002/02/16 09:15:33  richard
#forgot to patch bsddb backend too
#
#Revision 1.14  2002/01/22 07:21:13  richard
#. fixed back_bsddb so it passed the journal tests
#
#... it didn't seem happy using the back_anydbm _open method, which is odd.
#Yet another occurrance of whichdb not being able to recognise older bsddb
#databases. Yadda yadda. Made the HYPERDBDEBUG stuff more sane in the
#process.
#
#Revision 1.13  2001/12/10 22:20:01  richard
#Enabled transaction support in the bsddb backend. It uses the anydbm code
#where possible, only replacing methods where the db is opened (it uses the
#btree opener specifically.)
#Also cleaned up some change note generation.
#Made the backends package work with pydoc too.
#
#Revision 1.12  2001/11/21 02:34:18  richard
#Added a target version field to the extended issue schema
#
#Revision 1.11  2001/10/09 23:58:10  richard
#Moved the data stringification up into the hyperdb.Class class' get, set
#and create methods. This means that the data is also stringified for the
#journal call, and removes duplication of code from the backends. The
#backend code now only sees strings.
#
#Revision 1.10  2001/10/09 07:25:59  richard
#Added the Password property type. See "pydoc roundup.password" for
#implementation details. Have updated some of the documentation too.
#
#Revision 1.9  2001/08/12 06:32:36  richard
#using isinstance(blah, Foo) now instead of isFooType
#
#Revision 1.8  2001/08/07 00:24:42  richard
#stupid typo
#
#Revision 1.7  2001/08/07 00:15:51  richard
#Added the copyright/license notice to (nearly) all files at request of
#Bizar Software.
#
#Revision 1.6  2001/07/30 02:36:23  richard
#Handle non-existence of db files in the other backends (code from anydbm).
#
#Revision 1.5  2001/07/30 01:41:36  richard
#Makes schema changes mucho easier.
#
#Revision 1.4  2001/07/23 08:25:33  richard
#more handling of bad journals
#
#Revision 1.3  2001/07/23 08:20:44  richard
#Moved over to using marshal in the bsddb and anydbm backends.
#roundup-admin now has a "freshen" command that'll load/save all nodes (not
# retired - mod hyperdb.Class.list() so it lists retired nodes)
#
#Revision 1.2  2001/07/23 07:56:05  richard
#Storing only marshallable data in the db - no nasty pickled class references.
#
#Revision 1.1  2001/07/23 07:22:13  richard
#*sigh* some databases have _foo.so as their underlying implementation.
#This time for sure, Rocky.
#
#Revision 1.1  2001/07/23 07:15:57  richard
#Moved the backends into the backends package. Anydbm hasn't been tested at all.
#
#Revision 1.1  2001/07/23 06:23:41  richard
#moved hyper_bsddb.py to the new backends package as bsddb.py
#
#Revision 1.2  2001/07/22 12:09:32  richard
#Final commit of Grande Splite
#
#Revision 1.1  2001/07/22 11:58:35  richard
#More Grande Splite
#
