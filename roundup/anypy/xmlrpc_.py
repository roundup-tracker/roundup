try:
    # Python 3+.
    from xmlrpc import client, server
    server.SimpleXMLRPCDispatcher
except (ImportError, AttributeError):
    # Python 2.
    import SimpleXMLRPCServer as server
    import xmlrpclib as client  # noqa: F401
