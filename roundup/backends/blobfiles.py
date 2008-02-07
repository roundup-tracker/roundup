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
#$Id: blobfiles.py,v 1.24 2008-02-07 00:57:59 richard Exp $
'''This module exports file storage for roundup backends.
Files are stored into a directory hierarchy.
'''
__docformat__ = 'restructuredtext'

import os

def files_in_dir(dir):
    if not os.path.exists(dir):
        return 0
    num_files = 0
    for dir_entry in os.listdir(dir):
        full_filename = os.path.join(dir,dir_entry)
        if os.path.isfile(full_filename):
            num_files = num_files + 1
        elif os.path.isdir(full_filename):
            num_files = num_files + files_in_dir(full_filename)
    return num_files

class FileStorage:
    """Store files in some directory structure

    Some databases do not permit the storage of arbitrary data (i.e.,
    file content).  And, some database schema explicitly store file
    content in the fielsystem.  In particular, if a class defines a
    'filename' property, it is assumed that the data is stored in the
    indicated file, outside of whatever database Roundup is otherwise
    using.

    In these situations, it is difficult to maintain the transactional
    abstractions used elsewhere in Roundup.  In particular, if a
    file's content is edited, but then the containing transaction is
    not committed, we do not want to commit the edit.  Similarly, we
    would like to guarantee that if a transaction is committed to the
    database, then the edit has in fact taken place.

    This class provides an approximation of these transactional
    requirements.

    For classes that do not have a 'filename' property, the file name
    used to store the file's content is a deterministic function of
    the classname and nodeid for the file.  The 'filename' function
    computes this name.  The name will contain directories and
    subdirectories, but, suppose, for the purposes of what follows,
    that the filename is 'file'.

    Edit Procotol
    -------------
    
    When a file is created or edited, the following protocol is used:

    1. The new content of the file is placed in 'file.tmp'.

    2. A transaction is recored in 'self.transactions' referencing the
       'doStoreFile' method of this class.

    3. At some subsequent point, the database 'commit' function is
       called.  This function first performs a traditional database
       commit (for example, by issuing a SQL command to commit the
       current transaction), and, then, runs the transactions recored
       in 'self.transactions'.

    4. The 'doStoreFile' method renames the 'file.tmp' to 'file'.

    If Step 3 never occurs, but, instead, the database 'rollback'
    method is called, then that method, after rolling back the
    database transaction, calls 'rollbackStoreFile', which removes
    'file.tmp'.

    Race Condition
    --------------

    If two Roundup instances (say, the mail gateway and a web client,
    or two web clients running with a multi-process server) attempt
    edits at the same time, both will write to 'file.tmp', and the
    results will be indeterminate.
    
    Crash Analysis
    --------------
    
    There are several situations that may occur if a crash (whether
    because the machine crashes, because an unhandled Python exception
    is raised, or because the Python process is killed) occurs.
    
    Complexity ensues because backuping up an RDBMS is generally more
    complex than simply copying a file.  Instead, some command is run
    which stores a snapshot of the database in a file.  So, if you
    back up the database to a file, and then back up the filesystem,
    it is likely that further database transactions have occurred
    between the point of database backup and the point of filesystem
    backup.

    For the purposes, of this analysis, we assume that the filesystem
    backup occurred after the database backup.  Furthermore, we assume
    that filesystem backups are atomic; i.e., the at the filesystem is
    not being modified during the backup.

    1. Neither the 'commit' nor 'rollback' methods on the database are
       ever called.

       In this case, the '.tmp' file should be ignored as the
       transaction was not committed.

    2. The 'commit' method is called.  Subsequently, the machine
       crashes, and is restored from backups.

       The most recent filesystem backup and the most recent database
       backup are not in general from the same instant in time.

       This problem means that we can never be sure after a crash if
       the contents of a file are what we intend.  It is always
       possible that an edit was made to the file that is not
       reflected in the filesystem.

    3. A crash occurs between the point of the database commit and the
       call to 'doStoreFile'.

       If only one of 'file' and 'file.tmp' exists, then that
       version should be used.  However, if both 'file' and 'file.tmp'
       exist, there is no way to know which version to use.

    Reading the File
    ----------------

    When determining the content of the file, we use the following
    algorithm:

    1. If 'self.transactions' reflects an edit of the file, then use
       'file.tmp'.

       We know that an edit to the file is in process so 'file.tmp' is
       the right choice.  If 'file.tmp' does not exist, raise an
       exception; something has removed the content of the file while
       we are in the process of editing it.

    2. Otherwise, if 'file.tmp' exists, and 'file' does not, use
       'file.tmp'.

       We know that the file is supposed to exist because there is a
       reference to it in the database.  Since 'file' does not exist,
       we assume that Crash 3 occurred during the initial creation of
       the file.

    3. Otherwise, use 'file'.

       If 'file.tmp' is not present, this is obviously the best we can
       do.  This is always the right answer unless Crash 2 occurred,
       in which case the contents of 'file' may be newer than they
       were at the point of database backup.

       If 'file.tmp' is present, we know that we are not actively
       editing the file.  The possibilities are:

       a. Crash 1 has occurred.  In this case, using 'file' is the
          right answer, so we will have chosen correctly.

       b. Crash 3 has occurred.  In this case, 'file.tmp' is the right
          answer, so we will have chosen incorrectly.  However, 'file'
          was at least a previously committed value.

    Future Improvements
    -------------------

    One approach would be to take advantage of databases which do
    allow the storage of arbitary date.  For example, MySQL provides
    the HUGE BLOB datatype for storing up to 4GB of data.

    Another approach would be to store a version ('v') in the actual
    database and name files 'file.v'.  Then, the editing protocol
    would become:

    1. Generate a new version 'v', guaranteed to be different from all
       other versions ever used by the database.  (The version need
       not be in any particular sequence; a UUID would be fine.)

    2. Store the content in 'file.v'.

    3. Update the database to indicate that the version of the node is
       'v'.

    Now, if the transaction is committed, the database will refer to
    'file.v', where the content exists.  If the transaction is rolled
    back, or not committed, 'file.v' will never be referenced.  In the
    event of a crash, under the assumptions above, there may be
    'file.v' files that are not referenced by the database, but the
    database will be consistent, so long as unreferenced 'file.v'
    files are never removed until after the database has been backed
    up.
    """    

    tempext = '.tmp'
    """The suffix added to files indicating that they are uncommitted."""
    
    def __init__(self, umask):
        self.umask = umask

    def subdirFilename(self, classname, nodeid, property=None):
        """Determine what the filename and subdir for nodeid + classname is."""
        if property:
            name = '%s%s.%s'%(classname, nodeid, property)
        else:
            # roundupdb.FileClass never specified the property name, so don't
            # include it
            name = '%s%s'%(classname, nodeid)

        # have a separate subdir for every thousand messages
        subdir = str(int(nodeid) / 1000)
        return os.path.join(subdir, name)

    def _tempfile(self, filename):
        """Return a temporary filename.

        'filename' -- The name of the eventual destination file."""

        return filename + self.tempext

    def filename(self, classname, nodeid, property=None, create=0):
        '''Determine what the filename for the given node and optionally
        property is.

        Try a variety of different filenames - the file could be in the
        usual place, or it could be in a temp file pre-commit *or* it
        could be in an old-style, backwards-compatible flat directory.
        '''
        filename  = os.path.join(self.dir, 'files', classname,
                                 self.subdirFilename(classname, nodeid, property))
        # If the caller is going to create the file, return the
        # post-commit filename.  It is the callers responsibility to
        # add self.tempext when actually creating the file.
        if create:
            return filename

        tempfile = self._tempfile(filename)

        # If an edit to this file is in progress, then return the name
        # of the temporary file containing the edited content.
        for method, args in self.transactions:
            if (method == self.doStoreFile and
                    args == (classname, nodeid, property)):
                # There is an edit in progress for this file.
                if not os.path.exists(tempfile):
                    raise IOError('content file for %s not found'%tempfile)
                return tempfile

        if os.path.exists(filename):
            return filename

        # Otherwise, if the temporary file exists, then the probable 
        # explanation is that a crash occurred between the point that
        # the database entry recording the creation of the file
        # occured and the point at which the file was renamed from the
        # temporary name to the final name.
        if os.path.exists(tempfile):
            try:
                # Clean up, by performing the commit now.
                os.rename(tempfile, filename)
            except:
                pass
            # If two Roundup clients both try to rename the file
            # at the same time, only one of them will succeed.
            # So, tolerate such an error -- but no other.
            if not os.path.exists(filename):
                raise IOError('content file for %s not found'%filename)
            return filename

        # ok, try flat (very old-style)
        if property:
            filename = os.path.join(self.dir, 'files', '%s%s.%s'%(classname,
                nodeid, property))
        else:
            filename = os.path.join(self.dir, 'files', '%s%s'%(classname,
                nodeid))
        if os.path.exists(filename):
            return filename

        # file just ain't there
        raise IOError('content file for %s not found'%filename)

    def storefile(self, classname, nodeid, property, content):
        '''Store the content of the file in the database. The property may be
           None, in which case the filename does not indicate which property
           is being saved.
        '''
        # determine the name of the file to write to
        name = self.filename(classname, nodeid, property, create=1)

        # make sure the file storage dir exists
        if not os.path.exists(os.path.dirname(name)):
            os.makedirs(os.path.dirname(name))

        # save to a temp file
        name = self._tempfile(name)

        # make sure we don't register the rename action more than once
        if not os.path.exists(name):
            # save off the rename action
            self.transactions.append((self.doStoreFile, (classname, nodeid,
                property)))
        # always set umask before writing to make sure we have the proper one
        # in multi-tracker (i.e. multi-umask) or modpython scenarios
        # the umask may have changed since last we set it.
        os.umask(self.umask)
        open(name, 'wb').write(content)

    def getfile(self, classname, nodeid, property):
        '''Get the content of the file in the database.
        '''
        filename = self.filename(classname, nodeid, property)

        f = open(filename, 'rb')
        try:
            # snarf the contents and make sure we close the file
            return f.read()
        finally:
            f.close()

    def numfiles(self):
        '''Get number of files in storage, even across subdirectories.
        '''
        files_dir = os.path.join(self.dir, 'files')
        return files_in_dir(files_dir)

    def doStoreFile(self, classname, nodeid, property, **databases):
        '''Store the file as part of a transaction commit.
        '''
        # determine the name of the file to write to
        name = self.filename(classname, nodeid, property, 1)

        # the file is currently ".tmp" - move it to its real name to commit
        if name.endswith(self.tempext):
            # creation
            dstname = os.path.splitext(name)[0]
        else:
            # edit operation
            dstname = name
            name = self._tempfile(name)

        # content is being updated (and some platforms, eg. win32, won't
        # let us rename over the top of the old file)
        if os.path.exists(dstname):
            os.remove(dstname)

        os.rename(name, dstname)

        # return the classname, nodeid so we reindex this content
        return (classname, nodeid)

    def rollbackStoreFile(self, classname, nodeid, property, **databases):
        '''Remove the temp file as a part of a rollback
        '''
        # determine the name of the file to delete
        name = self.filename(classname, nodeid, property)
        if not name.endswith(self.tempext):
            name += self.tempext
        os.remove(name)

    def isStoreFile(self, classname, nodeid):
        '''See if there is actually any FileStorage for this node.
           Is there a better way than using self.filename?
        '''
        try:
            fname = self.filename(classname, nodeid)
            return True
        except IOError:
            return False

    def destroy(self, classname, nodeid):
        '''If there is actually FileStorage for this node
           remove it from the filesystem
        '''
        if self.isStoreFile(classname, nodeid):
            os.remove(self.filename(classname, nodeid))

# vim: set filetype=python ts=4 sw=4 et si
