roundup.anypy package - Python version compatibility layer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Roundup currently supports Python 2.3 to 2.6; however, some modules
have been introduced, while others have been deprecated.  The modules
in this package provide the functionalities which are used by Roundup

- adapting the most recent Python usage
- using new built-in functionality
- avoiding deprecation warnings

Use the modules in this package to preserve Roundup's compatibility.

sets_: sets compatibility module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since Python 2.4, there is a built-in type 'set'; therefore, the 'sets'
module is deprecated since version 2.6.  As far as Roundup is concerned,
the usage is identical; see 
http://docs.python.org/library/sets.html#comparison-to-the-built-in-set-types

Uses the built-in type 'set' if available, and thus avoids
deprecation warnings. Simple usage:

Change all::
  from sets import Set

to::
  from roundup.anypy.sets_ import set

and use 'set' instead of 'Set' (or sets.Set, respectively).
To avoid unnecessary imports, you can::

  try:
      set
  except NameError:
      from roundup.anypy.sets_ import set

hashlib_: md5/sha/hashlib compatibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The md5 and sha modules are deprecated since Python 2.6; the hashlib
module, introduced with Python 2.5, is recommended instead.

Change all::
  import md5
  md5.md5(), md5.new()
  import sha
  sha.sha(), sha.new()

to::
  from roundup.anypy.hashlib_ import md5
  md5()
  from roundup.anypy.hashlib_ import sha1
  sha1()

# vim: si
