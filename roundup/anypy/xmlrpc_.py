try:
    # Python 3+.
    from xmlrpc import client, server
    # If client.defusedxml == False, client.py will warn that
    # xmlrpc is insecure and defusedxml should be installed.
    client.defusedxml = False
    try:
        from defusedxml import xmlrpc
        xmlrpc.monkey_patch()
        # figure out how to allow user to set xmlrpc.MAX_DATA = bytes
        client.defusedxml = True
    except ImportError:
        # use regular xmlrpc with warnings
        pass

    server.SimpleXMLRPCDispatcher  # noqa: B018
except (ImportError, AttributeError):
    # Python 2.
    import SimpleXMLRPCServer as server
    import xmlrpclib as client  # noqa: F401
    client.defusedxml = False
