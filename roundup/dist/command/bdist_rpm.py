#
# Copyright (C) 2009 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#
from distutils.command.bdist_rpm import bdist_rpm as base
from distutils.file_util import write_file
import os

class bdist_rpm(base):

    def finalize_options(self):
        base.finalize_options(self)
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

