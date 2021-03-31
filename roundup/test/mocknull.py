
class MockNull:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            self.__dict__[key] = value

    def __call__(self, *args, **kwargs): return MockNull()
    def __getattr__(self, name):
        # This allows assignments which assume all intermediate steps are Null
        # objects if they don't exist yet.
        #
        # For example (with just 'client' defined):
        #
        # client.db.config.TRACKER_WEB = 'BASE/'
        self.__dict__[name] = MockNull()
        return getattr(self, name)

    def __getitem__(self, key): return self
    def __bool__(self): return False
    # Python 2 compatibility:
    __nonzero__ = __bool__
    def __contains__(self, key): return False
    def __eq__(self, rhs): return False
    def __ne__(self, rhs): return False
    def __str__(self): return ''
    def __repr__(self): return '<MockNull 0x%x>'%id(self)
    def gettext(self, str): return str
    _ = gettext
    def get(self, name, default=None):
        try:
            return self.__dict__[name.lower()]
        except KeyError:
            return default
