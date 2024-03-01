try:
    # Python 3+
    from http import client, server
except (ImportError, AttributeError):
    # Python 2.5-2.7
    import BaseHTTPServer as server  # noqa: F401
    import httplib as client  # noqa: F401
