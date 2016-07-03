
try:
    # Python 3+
    from urllib.parse import quote, urlencode, urlparse, parse_qs, urlunparse
except:
    # Python 2.5-2.7
    from urllib import quote, urlencode
    from urlparse import urlparse, parse_qs, urlunparse
