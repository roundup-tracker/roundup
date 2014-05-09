
try:
    # Python 3+
    from urllib.parse import quote, urlparse
except:
    # Python 2.5-2.7
    from urllib import quote
    from urlparse import urlparse
