try:
    # Python 3+
    from ssl import SSLError
except (ImportError, AttributeError):
    # Python 2.5-2.7
    from socket import sslerror as SSLError
