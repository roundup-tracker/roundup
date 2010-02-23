# In Python 3 the "anydbm" module was renamed to be "dbm" which is now a
# package containing the various implementations. The "wichdb" module's
# whichdb() function was moved to the new "dbm" module.

try:
    # old school first because <3 had a "dbm" module too...
    import anydbm
    from whichdb import whichdb
except ImportError:
    # python 3+
    import dbm as anydbm
    whichdb = anydbm.whichdb
