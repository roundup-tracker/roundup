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
# $Id: init.py,v 1.30 2004-07-27 00:57:18 richard Exp $

"""Init (create) a roundup instance.
"""
__docformat__ = 'restructuredtext'

import os, sys, errno, rfc822

import roundup.instance, password
from roundup import install_util

def copytree(src, dst, symlinks=0):
    """Recursively copy a directory tree using copyDigestedFile().

    The destination directory os allowed to exist.

    If the optional symlinks flag is true, symbolic links in the
    source tree result in symbolic links in the destination tree; if
    it is false, the contents of the files pointed to by symbolic
    links are copied.

    This was copied from shutil.py in std lib.
    """
    names = os.listdir(src)
    try:
        os.mkdir(dst)
    except OSError, error:
        if error.errno != errno.EEXIST: raise
    for name in names:
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        if symlinks and os.path.islink(srcname):
            linkto = os.readlink(srcname)
            os.symlink(linkto, dstname)
        elif os.path.isdir(srcname):
            copytree(srcname, dstname, symlinks)
        else:
            install_util.copyDigestedFile(srcname, dstname)

def install(instance_home, template):
    '''Install an instance using the named template and backend.

    'instance_home'
       the directory to place the instance data in
    'template'
       the directory holding the template to use in creating the instance data

    The instance_home directory will be created using the files found in
    the named template (roundup.templates.<name>). A standard instance_home
    contains:

    config.py
      simple configuration of things like the email address for the
      mail gateway, the mail domain, the mail host, ...
    dbinit.py and select_db.py
      defines the schema for the hyperdatabase and indicates which
      backend to use.
    interfaces.py
      defines the CGI Client and mail gateway MailGW classes that are
      used by roundup.cgi, roundup-server and roundup-mailgw.
    __init__.py
      ties together all the instance information into one interface
    db/
      the actual database that stores the instance's data
    html/
      the html templates that are used by the CGI Client
    detectors/
      the auditor and reactor modules for this instance
    '''
    # At the moment, it's just a copy
    copytree(template, instance_home)

    # rename the tempate in the TEMPLATE-INFO.txt file
    ti = loadTemplateInfo(instance_home)
    ti['name'] = ti['name'] + '-' + os.path.split(instance_home)[1]
    saveTemplateInfo(instance_home, ti)


def listTemplates(dir):
    ''' List all the Roundup template directories in a given directory.

        Find all the dirs that contain a TEMPLATE-INFO.txt and parse it.

        Return a list of dicts of info about the templates.
    '''
    ret = {}
    for idir in os.listdir(dir):
        idir = os.path.join(dir, idir)
        ti = loadTemplateInfo(idir)
        if ti:
            ret[ti['name']] = ti
    return ret

def loadTemplateInfo(dir):
    ''' Attempt to load a Roundup template from the indicated directory.

        Return None if there's no template, otherwise a template info
        dictionary.
    '''
    ti = os.path.join(dir, 'TEMPLATE-INFO.txt')
    if not os.path.exists(ti):
        return None

    # load up the template's information
    f = open(ti)
    try:
        m = rfc822.Message(open(ti))
        ti = {}
        ti['name'] = m['name']
        ti['description'] = m['description']
        ti['intended-for'] = m['intended-for']
        ti['path'] = dir
    finally:
        f.close()
    return ti

def writeHeader(name, value):
    ''' Write an rfc822-compatible header line, making it wrap reasonably
    '''
    out = [name.capitalize() + ':']
    n = len(out[0])
    for word in value.split():
        if len(word) + n > 74:
            out.append('\n')
            n = 0
        out.append(' ' + word)
        n += len(out[-1])
    return ''.join(out) + '\n'

def saveTemplateInfo(dir, info):
    ''' Save the template info (dict of values) to the TEMPLATE-INFO.txt
        file in the indicated directory.
    '''
    ti = os.path.join(dir, 'TEMPLATE-INFO.txt')
    f = open(ti, 'w')
    try:
        for name in 'name description intended-for path'.split():
            f.write(writeHeader(name, info[name]))
    finally:
        f.close()

def write_select_db(instance_home, backend):
    ''' Write the file that selects the backend for the tracker
    '''
    dbdir = os.path.join(instance_home, 'db')
    if not os.path.exists(dbdir):
        os.makedirs(dbdir)
    f = open(os.path.join(dbdir, 'backend_name'), 'w')
    f.write(backend+'\n')
    f.close()



# vim: set filetype=python ts=4 sw=4 et si
