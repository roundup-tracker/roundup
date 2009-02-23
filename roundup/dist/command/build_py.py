#
# Copyright (C) 2009 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#
from distutils.command.build_py import build_py

class build_py(build_py):

    def find_modules(self):
        # Files listed in py_modules are in the toplevel directory
        # of the source distribution.
        modules = []
        for module in self.py_modules:
            path = module.split('.')
            package = '.'.join(path[0:-1])
            module_base = path[-1]
            module_file = module_base + '.py'
            if self.check_module(module, module_file):
                modules.append((package, module_base, module_file))
        return modules


