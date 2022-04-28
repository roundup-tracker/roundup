#
# Copyright (C) 2009 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

import os, sys
import os.path
import glob

try:
    from setuptools.command.install import install as _build_py
    raise ImportError
except ImportError:
    from distutils.command.build import build as _build_py  # try/except clause
    orig_build = _build_py

try:
    # would be nice to use setuptools.Command.spawn() as it
    # obeys the dry-run flag.
    from subprocess import run as spawn
except ImportError:
    from distutils.spawn import spawn  # try/except: in except for subprocess

try:
    from distutils.spawn import find_executable # try/except: in try local find
except ImportError:
    from roundup.dist.command import find_executable

class build_doc(_build_py):
    """Defines the specific procedure to build roundup's documentation."""

    description = "build documentation"

    def run(self):
        """Run this command, i.e. do the actual document generation."""

        sphinx = find_executable('sphinx-build')
        if sphinx:
            sphinx = [sphinx]
        else:
            try:  # try to find version installed with Python tools
                  # tested with Sphinx 1.1.3
                import sphinx as sp
            except ImportError:
                pass
            else:
                sphinx = [sys.executable, sp.__file__]

        if not sphinx:
            self.warn("could not find sphinx-build in PATH")
            self.warn("cannot build documentation")
            return

        doc_dir = os.path.join('share', 'doc', 'roundup', 'html')
        temp_dir = os.path.join(self.build_temp, 'doc')
        cmd = sphinx + ['-d', temp_dir, 'doc', doc_dir]
        spawn(cmd)
