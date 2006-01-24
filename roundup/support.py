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

class PrioList:
    '''Manages a sorted list.

    Currently only implements method 'append' and iteration from a
    full list interface.
    Implementation: We manage a "sorted" status and sort on demand.
    Appending to the list will require re-sorting before use.
    >>> p = PrioList ()
    >>> for i in 5,7,1,-1 :
    ...  p.append (i)
    ...
    >>> for k in p :
    ...  print k
    ...
    -1
    1
    5
    7

    '''
    def __init__(self):
        self.list   = []
        self.sorted = True

    def append(self, item):
        self.list.append (item)
        self.sorted = False

    def __iter__(self):
        if not self.sorted :
            self.list.sort ()
            self.sorted = True
        return iter (self.list)

# vim: set et sts=4 sw=4 :
