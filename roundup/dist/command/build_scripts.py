#
# Copyright (C) 2009 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#
from distutils.command.build_scripts import build_scripts as base
from distutils import log
import sys, os, string

class build_scripts(base):
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
    package_name = 'roundup'

    def initialize_options(self):
        base.initialize_options(self)
        self.script_preamble = None
        self.target_platform = None
        self.python_executable = None

    def finalize_options(self):
        base.finalize_options(self)
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
        self.target_platform = target

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
            self.script_preamble = """
import sys
sys.path.insert(1, "%s/lib/python%s/site-packages")
"""%(prefix, version)
        else:
            self.script_preamble = ''

    def copy_scripts(self):
        """ Create each script listed in 'self.scripts'
        """

        to_module = string.maketrans('-/', '_.')

        self.mkpath(self.build_dir)
        for script in self.scripts:
            outfile = os.path.join(self.build_dir, os.path.basename(script))

            #if not self.force and not newer(script, outfile):
            #    self.announce("not copying %s (up-to-date)" % script)
            #    continue

            if self.dry_run:
                log.info("would create %s" % outfile)
                continue

            module = os.path.splitext(os.path.basename(script))[0]
            module = string.translate(module, to_module)
            script_vars = {
                'python': self.python_executable,
                'package': self.package_name,
                'module': module,
                'prefix': self.script_preamble,
            }

            log.info("writing %s" % outfile)
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
                os.chmod(outfile, 0o755)
