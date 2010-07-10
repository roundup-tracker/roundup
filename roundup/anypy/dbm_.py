# In Python 3 the "anydbm" module was renamed to be "dbm" which is now a
# package containing the various implementations. The "wichdb" module's
# whichdb() function was moved to the new "dbm" module.

import sys
if sys.version_info[:2] < (2, 6):
    def key_in(db, key):
        return db.has_key(key)
else:
    def key_in(db, key):
        return key in db

try:
    # old school first because <3 had a "dbm" module too...
    import anydbm
    from whichdb import whichdb
except ImportError:
    # python 3+
    import dbm as anydbm
    whichdb = anydbm.whichdb
