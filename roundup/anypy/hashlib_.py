"""
anypy.hashlib_: encapsulation of hashlib/md5/sha1/sha
"""

try:
    from hashlib import md5, sha1 # new in Python 2.5
except ImportError:
    from md5 import md5           # deprecated in Python 2.6
    from sha import sha as sha1   # deprecated in Python 2.6

# vim: ts=8 sts=4 sw=4 si
