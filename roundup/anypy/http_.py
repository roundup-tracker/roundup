try:
    # Python 3+
    from http import client, server
except:
    # Python 2.5-2.7
    import httplib as client
    import BaseHTTPServer as server

