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
#$Id: blobfiles.py,v 1.2 2002-02-27 03:40:59 richard Exp $
'''
This module exports file storage for roundup backends.
Files are stored into a directory hierarchy.
'''

import os, os.path

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
# TODO: maybe set "files"
#    def __init__(self):
#        pass

    def filename(self, classname, nodeid, property=None):
        '''Determine what the filename for the given node and optionally 
           property is.
        '''
        if property:
            name = '%s%s.%s'%(classname, nodeid, property)
        else:
            # roundupdb.FileClass never specified the property name, so don't 
            # include it
            name = '%s%s'%(classname, nodeid)

        # have a separate subdir for every thousand messages
        subdir = str(int(nodeid) / 1000)
        return os.path.join(self.dir, 'files', classname, subdir, name)

    def filename_flat(self, classname, nodeid, property=None):
        '''Determine what the filename for the given node and optionally 
           property is.
        '''
        if property:
            return os.path.join(self.dir, 'files', '%s%s.%s'%(classname,
                nodeid, property))
        else:
            # roundupdb.FileClass never specified the property name, so don't 
            # include it
            return os.path.join(self.dir, 'files', '%s%s'%(classname,
                nodeid))

    def storefile(self, classname, nodeid, property, content):
        '''Store the content of the file in the database. The property may be
           None, in which case the filename does not indicate which property
           is being saved.
        '''
        name = self.filename(classname, nodeid, property)
        if not os.path.exists(os.path.dirname(name)):
            os.makedirs(os.path.dirname(name))
        open(name + '.tmp', 'wb').write(content)
        self.transactions.append((self._doStoreFile, (name, )))


    def getfile(self, classname, nodeid, property):
        '''Get the content of the file in the database.
        '''
        filename = self.filename(classname, nodeid, property)
        try:
            return open(filename, 'rb').read()
        except:
            try:
                return open(filename+'.tmp', 'rb').read()
            except:
                # fallback to flat file storage
                filename = self.filename_flat(classname, nodeid, property)
                return open(filename, 'rb').read()

    def numfiles(self):
        '''Get number of files in storage, even across subdirectories.
        '''
        files_dir = os.path.join(self.dir, 'files')
        return files_in_dir(files_dir)

    def _doStoreFile(self, name, **databases):
        '''Must be implemented by subclass
        '''
    	raise NotImplementedError

