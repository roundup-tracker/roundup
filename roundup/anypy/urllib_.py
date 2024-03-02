
try:
    # Python 3+
    from urllib.parse import parse_qs, quote, unquote, urlencode, \
        urlparse, urlunparse
    from urllib.request import urlopen
except ImportError:
    # Python 2.5-2.7
    from urllib import quote, unquote, urlencode  # noqa: F401

    from urllib2 import urlopen  # noqa: F401
    from urlparse import parse_qs, urlparse, urlunparse  # noqa: F401
