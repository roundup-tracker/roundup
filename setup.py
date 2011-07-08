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
from roundup.dist.command.install_lib import install_lib
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
    # template munching
    packages = [
        'roundup',
        'roundup.anypy',
        'roundup.cgi',
        'roundup.cgi.PageTemplates',
        'roundup.cgi.TAL',
        'roundup.cgi.ZTUtils',
        'roundup.backends',
        'roundup.scripts',
    ]
    py_modules = ['roundup.demo',]

    # build list of scripts from their implementation modules
    scripts = [scriptname(f) for f in glob('roundup/scripts/[!_]*.py')]

    data_files = [
        ('share/roundup/cgi-bin', ['frontends/roundup.cgi']),
    ]
    # install man pages on POSIX platforms
    if os.name == 'posix':
        data_files.append(include('share/man/man1', '*'))

    # add the templates to the data files lists
    from roundup.init import listTemplates
    templates = [t['path']
                 for t in listTemplates('share/roundup/templates').values()]
    for tdir in templates:
        for idir in '. detectors extensions html'.split():
            data_files.append(include(os.path.join(tdir, idir), '*'))

    # add message files
    for (_dist_file, _mo_file) in list_message_files():
        data_files.append((os.path.dirname(_mo_file),
                           [os.path.join("build", _mo_file)]))

    # add docs
    data_files.append(include('share/doc/roundup/html', '*'))

    # perform the setup action
    from roundup import __version__

    # long_description may not contain non-ascii characters. Distutils
    # will produce an non-installable installer on linux *and* we can't
    # run the bdist_wininst on Linux if there are non-ascii characters
    # because the distutils installer will try to use the mbcs codec
    # which isn't available on non-windows platforms. See also
    # http://bugs.python.org/issue10945
    long_description=open('doc/announcement.txt').read().decode('utf8')
    try:
        long_description = long_description.encode('ascii')
    except UnicodeEncodeError, cause:
        print >> sys.stderr, "doc/announcement.txt contains non-ascii: %s" \
            % cause
        sys.exit(42)

    setup(name='roundup',
          version=__version__,
          author="Richard Jones",
          author_email="richard@users.sourceforge.net",
          description="A simple-to-use and -install issue-tracking system"
            " with command-line, web and e-mail interfaces. Highly"
            " customisable.",
          long_description=long_description,
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
                     'install_lib': install_lib,
                     },
          packages=packages,
          py_modules=py_modules,
          scripts=scripts,
          data_files=data_files)

if __name__ == '__main__':
    main()

# vim: set filetype=python sts=4 sw=4 et si :
