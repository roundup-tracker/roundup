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
# $Id: setup.py,v 1.96 2006-12-19 03:03:36 richard Exp $

from distutils.core import setup, Extension
from distutils.util import get_platform
from distutils.file_util import write_file
from distutils.command.bdist_rpm import bdist_rpm
from distutils.command.build import build
from distutils.command.build_scripts import build_scripts
from distutils.command.build_py import build_py

import sys, os, string
from glob import glob

# patch distutils if it can't cope with the "classifiers" keyword
from distutils.dist import DistributionMetadata
if not hasattr(DistributionMetadata, 'classifiers'):
    DistributionMetadata.classifiers = None
    DistributionMetadata.download_url = None

from roundup import msgfmt

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

        If the target platform is win32, create .bat files instead of
        *nix shell scripts.  Target platform is set to "win32" if main
        command is 'bdist_wininst' or if the command is 'bdist' and
        it has the list of formats (from command line or config file)
        and the first item on that list is wininst.  Otherwise
        target platform is set to current (build) platform.
    """
    package_name = None

    def initialize_options(self):
        build_scripts.initialize_options(self)
        self.script_preamble = None
        self.target_platform = None
        self.python_executable = None

    def finalize_options(self):
        build_scripts.finalize_options(self)
        cmdopt=self.distribution.command_options

        # find the target platform
        if self.target_platform:
            # TODO? allow explicit setting from command line
            target = self.target_platform
        if cmdopt.has_key("bdist_wininst"):
            target = "win32"
        elif cmdopt.get("bdist", {}).has_key("formats"):
            formats = cmdopt["bdist"]["formats"][1].split(",")
            if formats[0] == "wininst":
                target = "win32"
            else:
                target = sys.platform
            if len(formats) > 1:
                self.warn(
                    "Scripts are built for %s only (requested formats: %s)"
                    % (target, ",".join(formats)))
        else:
            # default to current platform
            target = sys.platform
        self.target_platfom = target

        # for native builds, use current python executable path;
        # for cross-platform builds, use default executable name
        if self.python_executable:
            # TODO? allow command-line option
            pass
        if target == sys.platform:
            self.python_executable = os.path.normpath(sys.executable)
        else:
            self.python_executable = "python"

        # for windows builds, add ".bat" extension
        if target == "win32":
            # *nix-like scripts may be useful also on win32 (cygwin)
            # to build both script versions, use:
            #self.scripts = list(self.scripts) + [script + ".bat"
            #    for script in self.scripts]
            self.scripts = [script + ".bat" for script in self.scripts]

        # tweak python path for installations outside main python library
        if cmdopt.get("install", {}).has_key("prefix"):
            prefix = os.path.expanduser(cmdopt['install']['prefix'][1])
            version = '%d.%d'%sys.version_info[:2]
            self.script_preamble = '''
import sys
sys.path.insert(1, "%s/lib/python%s/site-packages")
'''%(prefix, version)
        else:
            self.script_preamble = ''

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
                'python': self.python_executable,
                'package': self.package_name,
                'module': module,
                'prefix': self.script_preamble,
            }

            self.announce("creating %s" % outfile)
            file = open(outfile, 'w')

            try:
                # could just check self.target_platform,
                # but looking at the script extension
                # makes it possible to build both *nix-like
                # and windows-like scripts on win32.
                # may be useful for cygwin.
                if os.path.splitext(outfile)[1] == ".bat":
                    file.write('@echo off\n'
                        'if NOT "%%_4ver%%" == "" "%(python)s" -c "from %(package)s.scripts.%(module)s import run; run()" %%$\n'
                        'if     "%%_4ver%%" == "" "%(python)s" -c "from %(package)s.scripts.%(module)s import run; run()" %%*\n'
                        % script_vars)
                else:
                    file.write('#! %(python)s\n%(prefix)s'
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
    return script

### Build Roundup

def list_message_files(suffix=".po"):
    """Return list of all found message files and their intallation paths"""
    _files = glob("locale/*" + suffix)
    _list = []
    for _file in _files:
        # basename (without extension) is a locale name
        _locale = os.path.splitext(os.path.basename(_file))[0]
        _list.append((_file, os.path.join(
            "share", "locale", _locale, "LC_MESSAGES", "roundup.mo")))
    return _list

def check_manifest():
    """Check that the files listed in the MANIFEST are present when the
    source is unpacked.
    """
    try:
        f = open('MANIFEST')
    except:
        print '\n*** SOURCE WARNING: The MANIFEST file is missing!'
        return
    try:
        manifest = [l.strip() for l in f.readlines()]
    finally:
        f.close()
    err = [line for line in manifest if not os.path.exists(line)]
    if err:
        n = len(manifest)
        print '\n*** SOURCE WARNING: There are files missing (%d/%d found)!'%(
            n-len(err), n)
        print 'Missing:', '\nMissing: '.join(err)


class build_py_roundup(build_py):

    def find_modules(self):
        # Files listed in py_modules are in the toplevel directory
        # of the source distribution.
        modules = []
        for module in self.py_modules:
            path = string.split(module, '.')
            package = string.join(path[0:-1], '.')
            module_base = path[-1]
            module_file = module_base + '.py'
            if self.check_module(module, module_file):
                modules.append((package, module_base, module_file))
        return modules


class build_roundup(build):

    def build_message_files(self):
        """For each locale/*.po, build .mo file in target locale directory"""
        for (_src, _dst) in list_message_files():
            _build_dst = os.path.join("build", _dst)
            self.mkpath(os.path.dirname(_build_dst))
            self.announce("Compiling %s -> %s" % (_src, _build_dst))
            msgfmt.make(_src, _build_dst)

    def run(self):
        check_manifest()
        self.build_message_files()
        build.run(self)

class bdist_rpm_roundup(bdist_rpm):

    def finalize_options(self):
        bdist_rpm.finalize_options(self)
        if self.install_script:
            # install script is overridden.  skip default
            return
        # install script option must be file name.
        # create the file in rpm build directory.
        install_script = os.path.join(self.rpm_base, "install.sh")
        self.mkpath(self.rpm_base)
        self.execute(write_file, (install_script, [
                ("%s setup.py install --root=$RPM_BUILD_ROOT "
                    "--record=ROUNDUP_FILES") % self.python,
                # allow any additional extension for man pages
                # (rpm may compress them to .gz or .bz2)
                # man page here is any file
                # with single-character extension
                # in man directory
                "sed -e 's,\(/man/.*\..\)$,\\1*,' "
                    "<ROUNDUP_FILES >INSTALLED_FILES",
            ]), "writing '%s'" % install_script)
        self.install_script = install_script

#############################################################################
### Main setup stuff
#############################################################################

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
    templates = [t['path'] for t in listTemplates('templates').values()]
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

    # perform the setup action
    from roundup import __version__
    setup_args = {
        'name': "roundup",
        'version': __version__,
        'description': "A simple-to-use and -install issue-tracking system"
            " with command-line, web and e-mail interfaces. Highly"
            " customisable.",
        'long_description':
'''In this release
===============

Fixed in 1.3.2:

- relax rules for required fields in form_parser.py (sf bug 1599740)
- documentation cleanup from Luke Ross (sf patch 1594860)
- updated Spanish translation from Ramiro Morales (sf patch 1594718)
- handle 8-bit untranslateable messages in tracker templates
- handling of required for boolean False and numeric 0 (sf bug 1608200)
- removed bogus args attr of ConfigurationError (sf bug 1608056)
- implemented start_response in roundup.cgi (sf bug 1604304)
- clarified windows service documentation (sf patch 1597713)
- HTMLClass fixed to work with new item permissions check (sf bug 1602983)
- support POP over SSL (sf patch 1597703)
- clean up input field generation and quoting of values (sf bug 1615616)
- allow use of roundup-server pidfile without forking (sf bug 1614753)
- allow translation of status/priority menu options (sf bug 1613976)

New Features in 1.3.0:

- WSGI support via roundup.cgi.wsgi_handler

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
        'author': "Richard Jones",
        'author_email': "richard@users.sourceforge.net",
        'url': 'http://roundup.sourceforge.net/',
        'packages': packagelist,
        'classifiers': [
            'Development Status :: 5 - Production/Stable',
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
        'cmdclass': {
            'build_scripts': build_scripts_roundup,
            'build_py': build_py_roundup,
            'build': build_roundup,
            'bdist_rpm': bdist_rpm_roundup,
        },
        'scripts': roundup_scripts,

        'data_files':  installdatafiles
    }
    if sys.version_info[:2] > (2, 2):
       setup_args['py_modules'] = py_modules

    setup(**setup_args)

if __name__ == '__main__':
    main()

# vim: set filetype=python sts=4 sw=4 et si :
