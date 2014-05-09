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
"""Init (create) a roundup instance.
"""
__docformat__ = 'restructuredtext'

import os, errno, email.parser


from roundup import install_util, password
from roundup.configuration import CoreConfig
from roundup.i18n import _

def copytree(src, dst, symlinks=0):
    """Recursively copy a directory tree using copyDigestedFile().

    The destination directory is allowed to exist.

    If the optional symlinks flag is true, symbolic links in the
    source tree result in symbolic links in the destination tree; if
    it is false, the contents of the files pointed to by symbolic
    links are copied.

    This was copied from shutil.py in std lib.
    """

    # Prevent 'hidden' files (those starting with '.') from being considered.
    names = [f for f in os.listdir(src) if not f.startswith('.')]
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

def install(instance_home, template, settings={}):
    '''Install an instance using the named template and backend.

    'instance_home'
       the directory to place the instance data in
    'template'
       the directory holding the template to use in creating the instance data
    'settings'
       config.ini setting overrides (dictionary)

    The instance_home directory will be created using the files found in
    the named template (roundup.templates.<name>). A usual instance_home
    contains:

    config.ini
      tracker configuration file
    schema.py
      database schema definition
    initial_data.py
      database initialization script, used to populate the database
      with 'roundup-admin init' command
    interfaces.py
      (optional, not installed from standard templates) defines
      the CGI Client and mail gateway MailGW classes that are
      used by roundup.cgi, roundup-server and roundup-mailgw.
    db/
      the actual database that stores the instance's data
    html/
      the html templates that are used by the CGI Client
    detectors/
      the auditor and reactor modules for this instance
    extensions/
      code extensions to Roundup
    '''
    # At the moment, it's just a copy
    copytree(template, instance_home)

    # rename the tempate in the TEMPLATE-INFO.txt file
    ti = loadTemplateInfo(instance_home)
    ti['name'] = ti['name'] + '-' + os.path.split(instance_home)[1]
    saveTemplateInfo(instance_home, ti)

    # if there is no config.ini or old-style config.py
    # installed from the template, write default config text
    config_ini_file = os.path.join(instance_home, CoreConfig.INI_FILE)
    if not os.path.isfile(config_ini_file):
        config = CoreConfig(settings=settings)
        config.save(config_ini_file)


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

def loadTemplateInfo(path):
    ''' Attempt to load a Roundup template from the indicated directory.

        Return None if there's no template, otherwise a template info
        dictionary.
    '''
    tif = os.path.join(path, 'TEMPLATE-INFO.txt')
    if not os.path.exists(tif):
        return None

    if os.path.exists(os.path.join(path, 'config.py')):
        print _("WARNING: directory '%s'\n"
            "\tcontains old-style template - ignored"
            ) % os.path.abspath(path)
        return None

    # load up the template's information
    try:
        f = open(tif)
        m = email.parser.Parser().parse(f, True)
        ti = {}
        ti['name'] = m['name']
        ti['description'] = m['description']
        ti['intended-for'] = m['intended-for']
        ti['path'] = path
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

def write_select_db(instance_home, backend, dbdir = 'db'):
    ''' Write the file that selects the backend for the tracker
    '''
    # dbdir may be a relative pathname, os.path.join does the right
    # thing when the second component of a join is an absolute path
    dbdir = os.path.join (instance_home, dbdir)
    if not os.path.exists(dbdir):
        os.makedirs(dbdir)
    f = open(os.path.join(dbdir, 'backend_name'), 'w')
    f.write(backend+'\n')
    f.close()



# vim: set filetype=python sts=4 sw=4 et si :
