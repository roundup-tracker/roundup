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
# $Id: setup.py,v 1.46 2003-04-10 04:33:02 richard Exp $

from distutils.core import setup, Extension
from distutils.util import get_platform
from distutils.command.build_scripts import build_scripts

import sys, os, string
from glob import glob

# patch distutils if it can't cope with the "classifiers" keyword
if sys.version < '2.2.3':
    from distutils.dist import DistributionMetadata
    DistributionMetadata.classifiers = None
    DistributionMetadata.download_url = None

from roundup.templates.builder import makeHtmlBase


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
                        'if NOT "%%_4ver%%" == "" "%(python)s" -O -c "from %(package)s.scripts.%(module)s import run; run()" %%$\n'
                        'if     "%%_4ver%%" == "" "%(python)s" -O -c "from %(package)s.scripts.%(module)s import run; run()" %%*\n'
                        % script_vars)
                else:
                    file.write('#! %(python)s -O\n'
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

def main():
    # build list of scripts from their implementation modules
    roundup_scripts = map(scriptname, glob('roundup/scripts/[!_]*.py'))

    # template munching
    templates = map(os.path.basename, filter(isTemplateDir,
        glob(os.path.join('roundup', 'templates', '*'))))
    packagelist = [
        'roundup',
        'roundup.cgi',
        'roundup.cgi.PageTemplates',
        'roundup.cgi.TAL',
        'roundup.cgi.ZTUtils',
        'roundup.backends',
        'roundup.scripts',
        'roundup.templates'
    ]
    installdatafiles = [
        ('share/roundup/cgi-bin', ['cgi-bin/roundup.cgi']),
    ] 

    # install man pages on POSIX platforms
    if os.name == 'posix':
        installdatafiles.append(('man/man1', ['doc/roundup-admin.1',
            'doc/roundup-mailgw.1', 'doc/roundup-server.1']))

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
        download_url = 'http://sourceforge.net/project/showfiles.php?group_id=31577',
        packages = packagelist,
        classifiers = [
            'Development Status :: 4 - Beta',
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
        cmdclass = {
            'build_scripts': build_scripts_roundup,
        },
        scripts = roundup_scripts,

        data_files =  installdatafiles
    )

def install_demo():
    ''' Install a demo server for users to play with for instant gratification.

        Sets up the web service on localhost port 8080. Disables nosy lists.
    '''
    import shutil, socket, errno, BaseHTTPServer

    # create the instance
    home = os.path.abspath('demo')
    try:
        shutil.rmtree(home)
    except os.error, error:
        if error.errno != errno.ENOENT:
            raise
    from roundup import init, instance, password
    init.install(home, 'classic')
    # don't have email flying around
    os.remove(os.path.join(home, 'detectors', 'nosyreaction.py'))
    init.write_select_db(home, 'anydbm')

    # figure basic params for server
    hostname = socket.gethostname()
    port = 8080
    while 1:
        print 'Trying to set up web server on port %d ...'%port,
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.connect((hostname, port))
        except socket.error, e:
            if not hasattr(e, 'args') or e.args[0] != errno.ECONNREFUSED:
                raise
            print 'should be ok.'
            break
        else:
            s.close()
            print 'already in use.'
            port += 100
    url = 'http://%s:%s/demo/'%(hostname, port)

    # write the config
    f = open(os.path.join(home, 'config.py'), 'r')
    s = f.read().replace('http://tracker.example/cgi-bin/roundup.cgi/bugs/',
        url)
    f.close()
    f = open(os.path.join(home, 'config.py'), 'w')
    f.write(s)
    f.close()

    # initialise the database
    init.initialise(home, 'admin')

    # add the "demo" user
    tracker = instance.open(home)
    db = tracker.open('admin')
    db.user.create(username='demo', password=password.Password('demo'),
        realname='Demo User', roles='User')
    db.commit()
    db.close()

    # ok, so start up the server
    from roundup.scripts.roundup_server import RoundupRequestHandler
    RoundupRequestHandler.TRACKER_HOMES = {'demo': home}
    httpd = BaseHTTPServer.HTTPServer((hostname, port), RoundupRequestHandler)
    print 'Server running - connect to:\n  %s'%url
    print 'You may log in as "demo"/"demo" or "admin"/"admin".'
    print 'Hit Control-C to stop the server.'
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print 'Keyboard Interrupt: exiting'

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'demo':
        install_demo()
    else:
        main()

# vim: set filetype=python ts=4 sw=4 et si
