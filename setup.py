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
# $Id: setup.py,v 1.35 2002-06-17 23:14:44 richard Exp $

from distutils.core import setup, Extension
from distutils.util import get_platform
from distutils.command.build_scripts import build_scripts

import sys, os, string
from glob import glob

from roundup.templatebuilder import makeHtmlBase


#############################################################################
### Build script files
#############################################################################

class build_scripts_create(build_scripts):
    """ Overload the build_scripts command and create the scripts
        from scratch, depending on the target platform.

        You have to define the name of your package in an inherited
        class (due to the delayed instantiation of command classes
        in distutils, this cannot be passed to __init__).

        The scripts are created in an uniform scheme: they start the
        run() function in the module

            <packagename>.scripts.<mangled_scriptname>

        The mangling of script names replaces '-' and '/' characters
        with '-' and '.', so that they are valid module paths. 
    """
    package_name = None

    def copy_scripts(self):
        """ Create each script listed in 'self.scripts'
        """
        if not self.package_name:
            raise Exception("You have to inherit build_scripts_create and"
                " provide a package name")
        
        to_module = string.maketrans('-/', '_.')

        self.mkpath(self.build_dir)
        for script in self.scripts:
            outfile = os.path.join(self.build_dir, os.path.basename(script))

            #if not self.force and not newer(script, outfile):
            #    self.announce("not copying %s (up-to-date)" % script)
            #    continue

            if self.dry_run:
                self.announce("would create %s" % outfile)
                continue

            module = os.path.splitext(os.path.basename(script))[0]
            module = string.translate(module, to_module)
            script_vars = {
                'python': os.path.normpath(sys.executable),
                'package': self.package_name,
                'module': module,
            }

            self.announce("creating %s" % outfile)
            file = open(outfile, 'w')

            try:
                if sys.platform == "win32":
                    file.write('@echo off\n'
                        'if NOT "%%_4ver%%" == "" %(python)s -c "from %(package)s.scripts.%(module)s import run; run()" %%$\n'
                        'if     "%%_4ver%%" == "" %(python)s -c "from %(package)s.scripts.%(module)s import run; run()" %%*\n'
                        % script_vars)
                else:
                    file.write('#! %(python)s\n'
                        'from %(package)s.scripts.%(module)s import run\n'
                        'run()\n'
                        % script_vars)
            finally:
                file.close()
                os.chmod(outfile, 0755)


class build_scripts_roundup(build_scripts_create):
    package_name = 'roundup'


def scriptname(path):
    """ Helper for building a list of script names from a list of
        module files.
    """
    script = os.path.splitext(os.path.basename(path))[0]
    script = string.replace(script, '_', '-')
    if sys.platform == "win32":
        script = script + ".bat"
    return script



#############################################################################
### Main setup stuff
#############################################################################

def isTemplateDir(dir):
    return dir[0] != '.' and dir != 'CVS' and os.path.isdir(dir) \
        and os.path.isfile(os.path.join(dir, '__init__.py'))

# use that function to list all the templates
templates = map(os.path.basename, filter(isTemplateDir,
    glob(os.path.join('roundup', 'templates', '*'))))

def buildTemplates():
    for template in templates:
        tdir = os.path.join('roundup', 'templates', template)
        makeHtmlBase(tdir)

if __name__ == '__main__':
    # build list of scripts from their implementation modules
    roundup_scripts = map(scriptname, glob('roundup/scripts/[!_]*.py'))

    # template munching
    templates = map(os.path.basename, filter(isTemplateDir,
        glob(os.path.join('roundup', 'templates', '*'))))
    packagelist = [
        'roundup',
        'roundup.backends',
        'roundup.scripts',
        'roundup.templates'
    ]
    installdatafiles = [
        ('share/roundup/cgi-bin', ['cgi-bin/roundup.cgi']),
    ] 

    # munge the template HTML into the htmlbase module
    buildTemplates()

    # add the templates to the setup packages and data files lists
    for template in templates:
        tdir = os.path.join('roundup', 'templates', template)

        # add the template package and subpackage
        packagelist.append('roundup.templates.%s' % template)
        packagelist.append('roundup.templates.%s.detectors' % template)

        # scan for data files
        tfiles = glob(os.path.join(tdir, 'html', '*'))
        tfiles = filter(os.path.isfile, tfiles)
        installdatafiles.append(
            ('share/roundup/templates/%s/html' % template, tfiles)
        )

    # perform the setup action
    from roundup import __version__
    setup(
        name = "roundup", 
        version = __version__,
        description = "Roundup issue tracking system.",
        author = "Richard Jones",
        author_email = "richard@users.sourceforge.net",
        url = 'http://sourceforge.net/projects/roundup/',
        packages = packagelist,

        # Override certain command classes with our own ones
        cmdclass = {
            'build_scripts': build_scripts_roundup,
        },
        scripts = roundup_scripts,

        data_files =  installdatafiles
    )


#
# $Log: not supported by cvs2svn $
# Revision 1.34  2002/05/29 01:16:16  richard
# Sorry about this huge checkin! It's fixing a lot of related stuff in one go
# though.
#
# . #541941 ] changing multilink properties by mail
# . #526730 ] search for messages capability
# . #505180 ] split MailGW.handle_Message
#   - also changed cgi client since it was duplicating the functionality
# . build htmlbase if tests are run using CVS checkout (removed note from
#   installation.txt)
# . don't create an empty message on email issue creation if the email is empty
#
# Revision 1.33  2002/04/03 05:53:03  richard
# Didn't get around to committing these after the last release.
#
# Revision 1.32  2002/03/27 23:47:58  jhermann
# Fix for scripts running under CMD.EXE
#
# Revision 1.31  2002/03/22 18:36:00  jhermann
# chmod +x for scripts
#
# Revision 1.30  2002/01/29 20:07:15  jhermann
# Conversion to generated script stubs
#
# Revision 1.29  2002/01/23 06:05:36  richard
# prep work for release
#
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
