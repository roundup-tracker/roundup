# ruff: noqa: F401  - unused imports
try:
    # used for python2 and python 3 < 3.13
    import cgi
    from cgi import FieldStorage, MiniFieldStorage
except ImportError:
    # use for python3 >= 3.13
    from roundup.anypy.vendored import cgi
    from roundup.anypy.vendored.cgi import FieldStorage, MiniFieldStorage
