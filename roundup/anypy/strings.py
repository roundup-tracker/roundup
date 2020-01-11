# Roundup represents text internally using the native Python str type.
# In Python 3, these are Unicode strings.  In Python 2, these are
# encoded using UTF-8, and the Python 2 unicode type is only used in a
# few places, generally for interacting with external modules
# requiring that type to be used.

import sys
import io

_py3 = sys.version_info[0] > 2

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


def bs2b(s):
    """Convert a string object or UTF-8 encoded bytes to UTF-8 encoded bytes.
    """
    if _py3:
        if isinstance(s, bytes):
            return s
        else:
            return s.encode('utf-8')
    else:
        return s


def s2u(s, errors='strict'):
    """Convert a string object to a Unicode string."""
    if _py3:
        return s
    else:
        return unicode(s, 'utf-8', errors)  # noqa: 821


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
        if isinstance(s, unicode):    # noqa: 821
            return s
        else:
            return unicode(s, 'utf-8', errors)    # noqa: 821


def us2s(u):
    """Convert a string or Unicode string to the internal string format."""
    if _py3:
        return u
    else:
        if isinstance(u, unicode):    # noqa: 821
            return u.encode('utf-8')
        else:
            return u


def uany2s(u):
    """Convert a Unicode string or other object to the internal string format.

    Objects that are not Unicode strings are passed to str()."""
    if _py3:
        return str(u)
    else:
        if isinstance(u, unicode):    # noqa: 821
            return u.encode('utf-8')
        else:
            return str(u)


def is_us(s):
    """Return whether an object is a string or Unicode string."""
    if _py3:
        return isinstance(s, str)
    else:
        return isinstance(s, str) or isinstance(s, unicode)  # noqa: 821


def uchr(c):
    """Return the Unicode string containing the given character."""
    if _py3:
        return chr(c)
    else:
        return unichr(c)  # noqa: 821

# CSV files used for export and import represent strings in the style
# used by repr in Python 2; this means that each byte of the UTF-8
# representation is represented by a \x escape if not a printable
# ASCII character.  When such a representation is interpreted by eval
# in Python 3, the effect is that the Unicode characters in the
# resulting string correspond to UTF-8 bytes, so encoding the string
# as ISO-8859-1 produces the correct byte-string which must then be
# decoded as UTF-8 to produce the correct Unicode string.  The same
# representations are also used for journal storage in RDBMS
# databases, so that the database can be compatible between Python 2
# and Python 3.


def repr_export(v):
    """Return a Python-2-style representation of a value for export to CSV."""
    if _py3:
        if isinstance(v, str):
            return repr(s2b(v))[1:]
        elif isinstance(v, dict):
            repr_vals = []
            for key, value in sorted(v.items()):
                repr_vals.append('%s: %s' % (repr_export(key),
                                             repr_export(value)))
            return '{%s}' % ', '.join(repr_vals)
        else:
            return repr(v)
    else:
        return repr(v)


def eval_import(s):
    """Evaluate a Python-2-style value imported from a CSV file."""
    if _py3:
        v = eval(s)
        if isinstance(v, str):
            return v.encode('iso-8859-1').decode('utf-8')
        elif isinstance(v, dict):
            v_mod = {}
            for key, value in v.items():
                if isinstance(key, str):
                    key = key.encode('iso-8859-1').decode('utf-8')
                if isinstance(value, str):
                    value = value.encode('iso-8859-1').decode('utf-8')
                v_mod[key] = value
            return v_mod
        else:
            return v
    else:
        return eval(s)
