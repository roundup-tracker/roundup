#! /usr/bin/env python
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
# $Id: setup.py,v 1.29 2002-01-23 06:05:36 richard Exp $

from distutils.core import setup, Extension
from distutils.util import get_platform

from glob import glob
import sys,os
from roundup.templatebuilder import makeHtmlBase

def isTemplateDir(dir):
    return dir[0] != '.' and dir != 'CVS' and os.path.isdir(dir) \
        and os.path.isfile(os.path.join(dir, '__init__.py'))

templates = map(os.path.basename, filter(isTemplateDir,
    glob(os.path.join('roundup', 'templates', '*'))))
packagelist = [
    'roundup',
    'roundup.backends',
    'roundup.templates'
]
installdatafiles = [
    ('share/roundup/cgi-bin', ['cgi-bin/roundup.cgi']),
] 

for template in templates:
    tdir = os.path.join('roundup', 'templates', template)
    makeHtmlBase(tdir)

    # add the template package and subpackage
    packagelist.append('roundup.templates.%s' % template)
    packagelist.append('roundup.templates.%s.detectors' % template)

    # scan for data files
    tfiles = glob(os.path.join(tdir, 'html', '*'))
    tfiles = filter(os.path.isfile, tfiles)
    installdatafiles.append(
        ('share/roundup/templates/%s/html' % template, tfiles)
    )


setup(
    name = "roundup", 
    version = "0.4.0",
    description = "Roundup issue tracking system.",
    author = "Richard Jones",
    author_email = "richard@users.sourceforge.net",
    url = 'http://sourceforge.net/projects/roundup/',
    packages = packagelist,
    scripts = ['roundup-admin', 'roundup-mailgw', 'roundup-server'],
    data_files =  installdatafiles
)


#
# $Log: not supported by cvs2svn $
# Revision 1.28  2002/01/11 03:24:15  richard
# minor changes for 0.4.0b2
#
# Revision 1.27  2002/01/05 02:09:46  richard
# make setup abort if tests fail
#
# Revision 1.26  2001/12/08 07:06:20  jhermann
# Install html template files to share/roundup/templates
#
# Revision 1.25  2001/11/21 23:42:54  richard
# Some version number and documentation fixes.
#
# Revision 1.24  2001/11/06 22:32:15  jhermann
# Install roundup.cgi to share/roundup
#
# Revision 1.23  2001/10/17 06:04:00  richard
# Beginnings of an interactive mode for roundup-admin
#
# Revision 1.22  2001/10/11 05:01:28  richard
# Prep for pre-release #2
#
# Revision 1.21  2001/10/10 04:18:38  richard
# Getting ready for a preview release for 0.3.0.
#
# Revision 1.20  2001/10/08 21:49:30  richard
# Minor pre- 0.3.0 changes
#
# Revision 1.19  2001/09/10 09:48:35  richard
# Started changes log for 0.2.9
#
# Revision 1.18  2001/08/30 06:01:17  richard
# Fixed missing import in mailgw :(
#
# Revision 1.17  2001/08/08 03:29:35  richard
# Next release is 0.2.6
#
# Revision 1.16  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.15  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.14  2001/08/06 23:57:20  richard
# Am now bundling unittest with the package so that everyone can use the unit
# tests.
#
# Revision 1.13  2001/08/03 07:18:57  richard
# updated version number for 0.2.6
#
# Revision 1.12  2001/08/03 02:51:06  richard
# detect unit tests
#
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
