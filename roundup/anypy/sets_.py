"""
anypy.sets_: sets compatibility module

uses the built-in type 'set' if available, and thus avoids
deprecation warnings. Simple usage:

Change all
    from sets import Set
to
    from roundup.anypy.sets_ import set

and use 'set' instead of 'Set'.
To avoid unnecessary imports, you can:

    try:
        set
    except NameError:
        from roundup.anypy.sets_ import set

see:
http://docs.python.org/library/sets.html#comparison-to-the-built-in-set-types

"""

try:
    set = set                     # built-in since Python 2.4
except (NameError, TypeError):
    from sets import Set as set   # deprecated as of Python 2.6

# vim: ts=8 sts=4 sw=4 si et
