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
#$Id: back_bsddb3.py,v 1.15 2002-07-19 03:36:34 richard Exp $

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
        '''
        # attempt to open the journal - in some rare cases, the journal may
        # not exist
        try:
            db = bsddb3.btopen(os.path.join(self.dir, 'journals.%s'%classname),
                'r')
        except bsddb3._db.DBNoSuchFileError:
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
            db = bsddb3.btopen(os.path.join(self.dir, db_name), 'c')
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
#Revision 1.14  2002/07/14 02:05:54  richard
#. all storage-specific code (ie. backend) is now implemented by the backends
#
#Revision 1.13  2002/07/08 06:41:03  richard
#Was reopening the database with 'n'.
#
#Revision 1.12  2002/05/21 05:52:11  richard
#Well whadya know, bsddb3 works again.
#The backend is implemented _exactly_ the same as bsddb - so there's no
#using its transaction or locking support. It'd be nice to use those some
#day I suppose.
#
#Revision 1.11  2002/01/14 02:20:15  richard
# . changed all config accesses so they access either the instance or the
#   config attriubute on the db. This means that all config is obtained from
#   instance_config instead of the mish-mash of classes. This will make
#   switching to a ConfigParser setup easier too, I hope.
#
#At a minimum, this makes migration a _little_ easier (a lot easier in the
#0.5.0 switch, I hope!)
#
#Revision 1.10  2001/11/21 02:34:18  richard
#Added a target version field to the extended issue schema
#
#Revision 1.9  2001/10/09 23:58:10  richard
#Moved the data stringification up into the hyperdb.Class class' get, set
#and create methods. This means that the data is also stringified for the
#journal call, and removes duplication of code from the backends. The
#backend code now only sees strings.
#
#Revision 1.8  2001/10/09 07:25:59  richard
#Added the Password property type. See "pydoc roundup.password" for
#implementation details. Have updated some of the documentation too.
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
#Revision 1.4  2001/08/03 02:45:47  anthonybaxter
#'n' -> 'c' for create.
#
#Revision 1.3  2001/07/30 02:36:23  richard
#Handle non-existence of db files in the other backends (code from anydbm).
#
#Revision 1.2  2001/07/30 01:41:36  richard
#Makes schema changes mucho easier.
#
#Revision 1.1  2001/07/24 04:26:03  anthonybaxter
#bsddb3 implementation. For now, it's the bsddb implementation with a "3"
#added in crayon.
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
