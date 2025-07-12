#! /usr/bin/env python
# -*- coding: utf-8 -*-
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

from __future__ import print_function

import os
import sys
from glob import glob
from sysconfig import get_path

from setuptools import setup

from roundup.dist.command.bdist_rpm import bdist_rpm
from roundup.dist.command.build import build, list_message_files
from roundup.dist.command.build_doc import build_doc
from roundup.dist.command.install_lib import install_lib


def include(d, e):
    """Generate a pair of (directory, file-list) for installation.

    'd' -- A directory

    'e' -- A glob pattern"""

    return (d, [f for f in glob('%s/%s' % (d, e)) if os.path.isfile(f)])


def mapscript(path):
    """ Helper for building a list of script names from a list of
        module files.
    """
    module = os.path.splitext(os.path.basename(path))[0]
    script = module.replace('_', '-')
    return '%s = roundup.scripts.%s:run' % (script, module)


def make_data_files_absolute(data_files, prefix, enable=False):
    """Using setuptools data files are put under the egg install directory
       if the datafiles are relative paths. We don't want this. Data files
       like man pages, documentation, templates etc. should be installed
       in a directory outside of the install directory. So we prefix
       all datafiles making them absolute so man pages end up in places
       like: /usr/local/share/man, docs in /usr/local/share/doc/roundup,
       templates in /usr/local/share/roundup/templates.
    """
    new_data_files = [ (os.path.join(prefix,df[0]),df[1])
                       for df in data_files ]
    if enable:
        return new_data_files
    return data_files


def get_prefix():
    """Get site specific prefix using --prefix, platform lib or
       sys.prefix.
    """
    prefix_arg = False
    prefix = ""
    for a in sys.argv:
        if prefix_arg:
            prefix = a
            break

        # argv[0] can be a PosixPath when setup.py
        # is invoked by setuptools-py2cfg
        if not isinstance(a, str):
            continue

        # is there a short form -p or something for this??
        if a.startswith('--prefix'):
            if a == '--prefix':
                # next argument is prefix
                prefix_arg = True
                continue
            # strip '--prefix='
            prefix = a[9:]
    if prefix:
        return prefix

    if sys.platform.startswith('win'):
        # on windows, using pip to install and
        # prefixing data file paths with c:\path\a\b\...
        # results in treatment as a relative path.
        # The result is files are buried under:
        # platlib\path\a\b\...\share\ and not findable by
        # Roundup. So return no prefix which places the files at
        # platlib\share\{doc,locale,roundup} where roundup can
        # find templates/translations etc.
        # sigh....
        return ""

    # start with the platform library
    plp = get_path('platlib')
    # nuke suffix that matches lib/* and return prefix
    head, tail = os.path.split(plp)
    old_head = None
    while tail.lower() not in ['lib', 'lib64'] and head != old_head:
        old_head = head
        head, tail = os.path.split(head)
    if head == old_head:
        head = sys.prefix
    return head


def main():
    # template munching
    packages = [
        'roundup',
        'roundup.anypy',
        'roundup.anypy.vendored',
        'roundup.cgi',
        'roundup.cgi.PageTemplates',
        'roundup.cgi.TAL',
        'roundup.cgi.ZTUtils',
        'roundup.backends',
        'roundup.scripts',
        'roundup.test',
    ]

    # build list of scripts from their implementation modules
    scripts = [mapscript(f) for f in glob('roundup/scripts/[!_]*.py')]

    # build list of zope files/directories
    Zope = {}
    Zope['module'] = list(glob('frontends/ZRoundup/*.py'))
    Zope['module'].append('frontends/ZRoundup/refresh.txt')
    Zope['icons'] = list(glob('frontends/ZRoundupscripts/*.gif'))
    Zope['dtml'] = list(glob('frontends/ZRoundupscripts/*.dtml'))

    data_files = [
        ('share/roundup/cgi-bin', ['frontends/roundup.cgi']),
        ('share/roundup/frontends', ['frontends/wsgi.py']),
        ('share/roundup/frontends/ZRoundup', Zope['module']),
        ('share/roundup/frontends/ZRoundup/icons', Zope['icons']),
        ('share/roundup/frontends/ZRoundup/dtml', Zope['dtml']),
    ]
    # install man pages on POSIX platforms
    if os.name == 'posix':
        data_files.append(include('share/man/man1', '*'))

    # add the templates to the data files lists
    from roundup.init import listTemplates
    templates = [t['path']
                 for t in listTemplates('share/roundup/templates').values()]
    for tdir in templates:
        for idir in '. detectors extensions html html/layout static'.split():
            data_files.append(include(os.path.join(tdir, idir), '*'))

    # add message files
    for (_dist_file, _mo_file) in list_message_files():
        data_files.append((os.path.dirname(_mo_file),
                           [os.path.join("build", _mo_file)]))

    # add docs
    data_files.append(include('share/doc/roundup/html', '*'))
    data_files.append(include('share/doc/roundup/html/_images', '*'))
    data_files.append(include('share/doc/roundup/html/_sources', '*'))
    data_files.append(include('share/doc/roundup/html/_static', '*'))

    data_files = make_data_files_absolute(data_files, get_prefix())

    # when running under python2, even if called from setup, it tries
    # and fails to perform an egg easy install even though it shouldn't:
    # https://issues.roundup-tracker.org/issue2551185
    # Add this argument if we are an install to prevent this.
    # This works right under python3.
    # FIXME there has to be a better way than this
    # https://issues.roundup-tracker.org/issue2551185

    if sys.version_info[0] < 3:
        for arg in sys.argv:
            if arg == 'install':
                sys.argv.append('--old-and-unmanageable')

    # perform the setup action
    from roundup import __version__

    # long_description may not contain non-ascii characters. Distutils
    # will produce an non-installable installer on linux *and* we can't
    # run the bdist_wininst on Linux if there are non-ascii characters
    # because the distutils installer will try to use the mbcs codec
    # which isn't available on non-windows platforms. See also
    # http://bugs.python.org/issue10945
    with open('doc/announcement.txt') as announcement:
        long_description = announcement.read()
    try:
        # attempt to interpret string as 'ascii'
        long_description.encode('ascii')
    except UnicodeEncodeError as cause:
        print("doc/announcement.txt contains non-ascii: %s"
              % cause, file=sys.stderr)
        sys.exit(42)

    setup(name='roundup',
          author="Richard Jones",
          author_email="richard@users.sourceforge.net",
          classifiers=['Development Status :: 5 - Production/Stable',
                       #'Development Status :: 4 - Beta',
                       #'Development Status :: 3 - Alpha',
                       'Environment :: Console',
                       'Environment :: Web Environment',
                       'Intended Audience :: Customer Service',
                       'Intended Audience :: Information Technology',
                       'Intended Audience :: End Users/Desktop',
                       'Intended Audience :: Developers',
                       'Intended Audience :: System Administrators',
                       'License :: OSI Approved',
                       'License :: OSI Approved :: MIT License',
                       'License :: OSI Approved :: Zope Public License',
                       'License :: OSI Approved :: Python Software Foundation License',
                       'Operating System :: MacOS :: MacOS X',
                       'Operating System :: Microsoft :: Windows',
                       'Operating System :: POSIX',
                       'Programming Language :: Python',
                       'Programming Language :: Python :: 3',
                       'Programming Language :: Python :: 3.7',
                       'Programming Language :: Python :: 3.8',
                       'Programming Language :: Python :: 3.9',
                       'Programming Language :: Python :: 3.10',
                       'Programming Language :: Python :: 3.11',
                       'Programming Language :: Python :: 3.12',
                       'Programming Language :: Python :: 3.13',
                       'Programming Language :: Python :: Implementation :: CPython',
                       'Topic :: Communications :: Email',
                       'Topic :: Office/Business',
                       'Topic :: Software Development :: Bug Tracking',
                       'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
                       ],
          # Override certain command classes with our own ones
          cmdclass={'build_doc': build_doc,
                     'build': build,
                     'bdist_rpm': bdist_rpm,
                     'install_lib': install_lib,
                     },
          data_files=data_files,
          description="A simple-to-use and -install issue-tracking system"
            " with command-line, web and e-mail interfaces. Highly"
            " customisable.",
          download_url='https://pypi.org/project/roundup',
          entry_points={
              'console_scripts': scripts,
          },
          extras_require={
              "charting": ['pygal'],
              "jinja2": ['jinja2'],
              "extras": ['brotli', 'pytz'],
              "test": ['pytest > 7.0.0'],
              },
          license="OSI Approved: MIT License, Zope Public License,"
                  " Python Software Foundation License",
          long_description=long_description,
          long_description_content_type='text/x-rst',
          maintainer="Ralf Schlatterbeck",
          maintainer_email="rsc@runtux.com",
          packages=packages,
          project_urls={
              "Documentation": "https://roundup-tracker.org/docs.html",
              "Changelog": "https://sourceforge.net/p/roundup/code/ci/tip/tree/CHANGES.txt",
              "Contact": "https://roundup-tracker.org/contact.html",
              "IRC": "https://webchat.oftc.net/?randomnick=1&channels=roundup&prompt=1",
              "Issues": "https://issues.roundup-tracker.org/",
              "Licenses": "https://roundup-tracker.org/docs/license.html",
              "Wiki": "https://wiki.roundup-tracker.org/",
    },
          python_requires=">=3.7",
          url='https://www.roundup-tracker.org',
          version=__version__,
)


if __name__ == '__main__':

    # Prevent `pip install roundup` from building bdist_wheel.
    # Man pages, templates, locales installed under site-packages not
    #  in normal system locations.
    # https://stackoverflow.com/questions/36846260/can-python-setuptools-install-files-outside-dist-packages
    '''
    if 'bdist_wheel' in sys.argv:
        raise RuntimeError("This setup.py does not support wheels")
    '''

    os.chdir(os.path.dirname(__file__) or '.')
    main()

# vim: set filetype=python sts=4 sw=4 et si :
