"""Implements various support classes and functions used in a number of
places in Roundup code.
"""

__docformat__ = 'restructuredtext'

import os

class TruthDict:
    '''Returns True for valid keys, False for others.
    '''
    def __init__(self, keys):
        if keys:
            self.keys = {}
            for col in keys:
                self.keys[col] = 1
        else:
            self.__getitem__ = lambda name: 1

    def __getitem__(self, name):
        return self.keys.has_key(name)

def ensureParentsExist(dest):
    if not os.path.exists(os.path.dirname(dest)):
        os.makedirs(os.path.dirname(dest))

# vim: set et sts=4 sw=4 :
