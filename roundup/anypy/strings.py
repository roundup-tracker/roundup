# Roundup represents text internally using the native Python str type.
# In Python 3, these are Unicode strings.  In Python 2, these are
# encoded using UTF-8, and the Python 2 unicode type is only used in a
# few places, generally for interacting with external modules
# requiring that type to be used.

import sys
_py3 = sys.version_info[0] > 2

import io
if _py3:
    StringIO = io.StringIO
else:
    StringIO = io.BytesIO

def b2s(b):
    """Convert a UTF-8 encoded bytes object to the internal string format."""
    if _py3:
        return b.decode('utf-8')
    else:
        return b

def s2b(s):
    """Convert a string object to UTF-8 encoded bytes."""
    if _py3:
        return s.encode('utf-8')
    else:
        return s

def s2u(s, errors='strict'):
    """Convert a string object to a Unicode string."""
    if _py3:
        return s
    else:
        return unicode(s, 'utf-8', errors)

def u2s(u):
    """Convert a Unicode string to the internal string format."""
    if _py3:
        return u
    else:
        return u.encode('utf-8')

def us2u(s, errors='strict'):
    """Convert a string or Unicode string to a Unicode string."""
    if _py3:
        return s
    else:
        if isinstance(s, unicode):
            return s
        else:
            return unicode(s, 'utf-8', errors)

def us2s(u):
    """Convert a string or Unicode string to the internal string format."""
    if _py3:
        return u
    else:
        if isinstance(u, unicode):
            return u.encode('utf-8')
        else:
            return u

def uany2s(u):
    """Convert a Unicode string or other object to the internal string format.

    Objects that are not Unicode strings are passed to str()."""
    if _py3:
        return str(u)
    else:
        if isinstance(u, unicode):
            return u.encode('utf-8')
        else:
            return str(u)

def is_us(s):
    """Return whether an object is a string or Unicode string."""
    if _py3:
        return isinstance(s, str)
    else:
        return isinstance(s, str) or isinstance(s, unicode)

def uchr(c):
    """Return the Unicode string containing the given character."""
    if _py3:
        return chr(c)
    else:
        return unichr(c)
