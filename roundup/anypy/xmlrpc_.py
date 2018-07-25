try:
    # Python 3+.
    from xmlrpc import client, server
except ImportError:
    # Python 2.
    import xmlrpclib as client
    import SimpleXMLRPCServer as server
