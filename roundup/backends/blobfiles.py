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
#$Id: blobfiles.py,v 1.19 2005-06-08 03:35:18 anthonybaxter Exp $
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
    """Store files in some directory structure"""    
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
    
    def filename(self, classname, nodeid, property=None, create=0):
        '''Determine what the filename for the given node and optionally 
        property is.

        Try a variety of different filenames - the file could be in the
        usual place, or it could be in a temp file pre-commit *or* it
        could be in an old-style, backwards-compatible flat directory.
        '''
        filename  = os.path.join(self.dir, 'files', classname,
                                 self.subdirFilename(classname, nodeid, property))
        if create or os.path.exists(filename):
            return filename

        # try .tmp
        filename = filename + '.tmp'
        if os.path.exists(filename):
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
        name = name + '.tmp'

        # make sure we don't register the rename action more than once
        if not os.path.exists(name):
            # save off the rename action
            self.transactions.append((self.doStoreFile, (classname, nodeid,
                property)))
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
        name = self.filename(classname, nodeid, property)

        # the file is currently ".tmp" - move it to its real name to commit
        if name.endswith('.tmp'):
            # creation
            dstname = os.path.splitext(name)[0]
        else:
            # edit operation
            dstname = name
            name = name + '.tmp'

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
        if not name.endswith('.tmp'):
            name += '.tmp'
        os.remove(name)

# vim: set filetype=python ts=4 sw=4 et si
