
try:
    # Python 3+
    from urllib.parse import quote, unquote, urlencode, urlparse, parse_qs, \
        urlunparse
    from urllib.request import urlopen
except ImportError:
    # Python 2.5-2.7
    from urllib import quote, unquote, urlencode         # noqa: F401
    from urllib2 import urlopen                          # noqa: F401
    from urlparse import urlparse, parse_qs, urlunparse  # noqa: F401
