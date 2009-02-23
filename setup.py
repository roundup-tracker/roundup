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


from roundup.dist.command.build_doc import build_doc
from roundup.dist.command.build_scripts import build_scripts
from roundup.dist.command.build_py import build_py
from roundup.dist.command.build import build, list_message_files
from roundup.dist.command.bdist_rpm import bdist_rpm
from distutils.core import setup

import sys, os
from glob import glob

# patch distutils if it can't cope with the "classifiers" keyword
from distutils.dist import DistributionMetadata
if not hasattr(DistributionMetadata, 'classifiers'):
    DistributionMetadata.classifiers = None
    DistributionMetadata.download_url = None

def include(d, e):
    """Generate a pair of (directory, file-list) for installation.

    'd' -- A directory

    'e' -- A glob pattern"""
    
    return (d, [f for f in glob('%s/%s'%(d, e)) if os.path.isfile(f)])

def scriptname(path):
    """ Helper for building a list of script names from a list of
        module files.
    """
    script = os.path.splitext(os.path.basename(path))[0]
    script = script.replace('_', '-')
    return script

def main():
    # build list of scripts from their implementation modules
    roundup_scripts = map(scriptname, glob('roundup/scripts/[!_]*.py'))

    # template munching
    packagelist = [
        'roundup',
        'roundup.cgi',
        'roundup.cgi.PageTemplates',
        'roundup.cgi.TAL',
        'roundup.cgi.ZTUtils',
        'roundup.backends',
        'roundup.scripts',
    ]
    installdatafiles = [
        ('share/roundup/cgi-bin', ['frontends/roundup.cgi']),
    ]
    py_modules = ['roundup.demo',]

    # install man pages on POSIX platforms
    if os.name == 'posix':
        installdatafiles.append(('man/man1', ['doc/roundup-admin.1',
            'doc/roundup-mailgw.1', 'doc/roundup-server.1',
            'doc/roundup-demo.1']))

    # add the templates to the data files lists
    from roundup.init import listTemplates
    templates = [t['path'] for t in listTemplates(os.path.join('share','roundup','templates')).values()]
    for tdir in templates:
        # scan for data files
        for idir in '. detectors extensions html'.split():
            idir = os.path.join(tdir, idir)
            if not os.path.isdir(idir):
                continue
            tfiles = []
            for f in os.listdir(idir):
                if f.startswith('.'):
                    continue
                ifile = os.path.join(idir, f)
                if os.path.isfile(ifile):
                    tfiles.append(ifile)
            installdatafiles.append(
                (os.path.join('share', 'roundup', idir), tfiles)
            )

    # add message files
    for (_dist_file, _mo_file) in list_message_files():
        installdatafiles.append((os.path.dirname(_mo_file),
            [os.path.join("build", _mo_file)]))

    # add docs
    installdatafiles.append(include(os.path.join('share', 'doc', 'roundup', 'html'), '*'))

    # perform the setup action
    from roundup import __version__
    
    setup(name='roundup',
          version=__version__,
          author="Richard Jones",
          author_email="richard@users.sourceforge.net",
          description='Issue-tracking System.',
          long_description="""Roundup is a simple-to-use and -install issue-tracking system
with command-line, web and e-mail interfaces. Highly customisable.""",
          url='http://www.roundup-tracker.org',
          download_url='http://pypi.python.org/pypi/roundup',
          classifiers=['Development Status :: 5 - Production/Stable',
                       'Environment :: Console',
                       'Environment :: Web Environment',
                       'Intended Audience :: End Users/Desktop',
                       'Intended Audience :: Developers',
                       'Intended Audience :: System Administrators',
                       'License :: OSI Approved :: Python Software Foundation License',
                       'Operating System :: MacOS :: MacOS X',
                       'Operating System :: Microsoft :: Windows',
                       'Operating System :: POSIX',
                       'Programming Language :: Python',
                       'Topic :: Communications :: Email',
                       'Topic :: Office/Business',
                       'Topic :: Software Development :: Bug Tracking',
                       ],

          # Override certain command classes with our own ones
          cmdclass= {'build_doc': build_doc,
                     'build_scripts': build_scripts,
                     'build_py': build_py,
                     'build': build,
                     'bdist_rpm': bdist_rpm,
                     },
          packages=packagelist,
          py_modules=py_modules,
          scripts=roundup_scripts,
          data_files=installdatafiles)

if __name__ == '__main__':
    main()

# vim: set filetype=python sts=4 sw=4 et si :
