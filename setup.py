#! /usr/bin/env python
# $Id: setup.py,v 1.12 2001-08-03 02:51:06 richard Exp $

from distutils.core import setup, Extension
from distutils.util import get_platform

from glob import glob
import os
from roundup.templatebuilder import makeHtmlBase

try:
    import unittest
except:
    print 'Skipping unit tests (no unittest module found)'
else:
    print 'Running unit tests...'
    import test
    test.go()

templates = 'classic', 'extended'
packagelist = [ 'roundup', 'roundup.backends', 'roundup.templates' ]
installdatafiles = []

for t in templates:
    makeHtmlBase(os.path.join('roundup', 'templates', t))
    packagelist.append('roundup.templates.%s'%t)
    packagelist.append('roundup.templates.%s.detectors'%t)
    tfiles = glob(os.path.join('roundup','templates', t, 'html', '*'))
    tfiles = filter(os.path.isfile, tfiles)


setup ( name = "roundup", 
        version = "0.2.5",
        description = "Roundup issue tracking system.",
        author = "Richard Jones",
        author_email = "richard@sourceforge.net",
        url = 'http://sourceforge.net/projects/roundup/',
        packages = packagelist,
        scripts = ['roundup-admin', 'roundup-mailgw', 'roundup-server']
)

#
# $Log: not supported by cvs2svn $
# Revision 1.11  2001/08/03 01:54:58  richard
# Started stuff off for the 0.2.5 release
#
# Revision 1.10  2001/07/30 07:17:44  richard
# Just making sure we've got the right version in there for development.
#
# Revision 1.9  2001/07/29 23:34:26  richard
# Added unit tests so they're run whenever we package/install/whatever.
#
# Revision 1.8  2001/07/29 09:43:46  richard
# Make sure that the htmlbase is up-to-date when we build a source dist.
#
# Revision 1.7  2001/07/29 08:37:58  richard
# changes
#
# Revision 1.6  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.5  2001/07/28 00:39:18  richard
# changes for the 0.2.1 distribution build.
#
# Revision 1.4  2001/07/27 07:20:17  richard
# Makefile is now obsolete - setup does what it used to do.
#
# Revision 1.3  2001/07/27 06:56:25  richard
# Added scripts to the setup and added the config so the default script
# install dir is /usr/local/bin.
#
# Revision 1.2  2001/07/26 07:14:27  richard
# Made setup.py executable, added id and log.
#
#
#
# vim: set filetype=python ts=4 sw=4 et si
