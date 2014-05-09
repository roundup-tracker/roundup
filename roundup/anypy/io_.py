
try:
    # Python 2.6+, 3+
    from io import StringIO, BytesIO
except:
    # Python 2.5
    from StringIO import StringIO
    BytesIO = StringIO

