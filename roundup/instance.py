# $Id: instance.py,v 1.1 2001-08-05 07:43:52 richard Exp $

''' Currently this module provides one function: open. This function opens
an instance.
'''

import imp

class Opener:
    def __init__(self):
        self.number = 0
        self.instances = {}

    def open(self, instance_home):
        if self.instances.has_key(instance_home):
            return imp.load_package(self.instances[instance_home],
                instance_home)
        self.number = self.number + 1
        modname = '_roundup_instance_%s'%self.number
        self.instances[instance_home] = modname
        return imp.load_package(modname, instance_home)

opener = Opener()
open = opener.open

del Opener
del opener


#
# $Log: not supported by cvs2svn $
#
#
# vim: set filetype=python ts=4 sw=4 et si
