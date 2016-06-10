#
# Copyright (C) 2009 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

import os, sys
import os.path
import glob

from distutils.command import build
from distutils.spawn import spawn, find_executable
from distutils.dep_util import newer, newer_group
from distutils.dir_util import copy_tree, remove_tree, mkpath
from distutils.file_util import copy_file
from distutils import sysconfig

class build_doc(build.build):
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
