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

    setup(name='roundup',
          version=__version__,
          author="Richard Jones",
          author_email="richard@users.sourceforge.net",
          description="A simple-to-use and -install issue-tracking system"
            " with command-line, web and e-mail interfaces. Highly"
            " customisable.",
          long_description='''
1.4.8 fixes some regressions:

- bug introduced into hyperdb filter (issue 2550505)
- bug introduced into CVS export and view (issue 2550529)
- bugs introduced in the migration to the email package (issue 2550531)

And adds a couple of other fixes:

- handle bogus pagination values (issue 2550530)
- fix TLS handling with some SMTP servers (issues 2484879 and 1912923)

If you're upgrading from an older version of Roundup you *must* follow
the "Software Upgrade" guidelines given in the maintenance documentation.

Roundup requires python 2.3 or later for correct operation.

To give Roundup a try, just download (see below), unpack and run::

    roundup-demo

Documentation is available at the website:
     http://roundup.sourceforge.net/
Mailing lists - the place to ask questions:
     http://sourceforge.net/mail/?group_id=31577

About Roundup
=============

Roundup is a simple-to-use and -install issue-tracking system with
command-line, web and e-mail interfaces. It is based on the winning design
from Ka-Ping Yee in the Software Carpentry "Track" design competition.

Note: Ping is not responsible for this project. The contact for this
project is richard@users.sourceforge.net.

Roundup manages a number of issues (with flexible properties such as
"description", "priority", and so on) and provides the ability to:

(a) submit new issues,
(b) find and edit existing issues, and
(c) discuss issues with other participants.

The system will facilitate communication among the participants by managing
discussions and notifying interested parties when issues are edited. One of
the major design goals for Roundup that it be simple to get going. Roundup
is therefore usable "out of the box" with any python 2.3+ installation. It
doesn't even need to be "installed" to be operational, though a
disutils-based install script is provided.

It comes with two issue tracker templates (a classic bug/feature tracker and
a minimal skeleton) and five database back-ends (anydbm, sqlite, metakit,
mysql and postgresql).
''',
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
          packages=packages,
          py_modules=py_modules,
          scripts=scripts,
          data_files=data_files)

if __name__ == '__main__':
    main()

# vim: set filetype=python sts=4 sw=4 et si :
