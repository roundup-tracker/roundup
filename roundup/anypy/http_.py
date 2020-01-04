try:
    # Python 3+
    from http import client, server
    server.DEFAULT_ERROR_MESSAGE
except (ImportError, AttributeError):
    # Python 2.5-2.7
    import httplib as client
    import BaseHTTPServer as server
